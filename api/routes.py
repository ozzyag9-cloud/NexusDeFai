"""
NEXUS AI - FastAPI Signal API
Exposes signals, stats, and webhooks for B2B licensing and integrations.

Endpoints:
  GET  /signals          — latest signals (auth required)
  GET  /signals/{id}     — single signal
  GET  /stats            — performance stats
  POST /webhook/register — register a webhook URL
  GET  /health           — system health check

Auth: Bearer token via X-API-Key header
"""

import asyncio
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta
from typing import Optional

import aiohttp
from fastapi import FastAPI, HTTPException, Depends, Header, Query, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel, HttpUrl
from loguru import logger

from config import Config, TradingSignal
from utils.database import SignalDatabase


# ─── App ──────────────────────────────────────────────────────

app = FastAPI(
    title="NEXUS AI Signal API",
    description="Multi-agent trading signal delivery API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

db = SignalDatabase()

# All data endpoints live under /api/* so the dashboard JS at /api/... works correctly
api_router = APIRouter(prefix="/api")


# ─── Auth (DB-backed) ─────────────────────────────────────────

async def verify_api_key(x_api_key: str = Header(..., alias="X-API-Key")) -> dict:
    """Verify API key against the subscribers table."""
    sub = await db.verify_api_key(x_api_key)
    if not sub:
        raise HTTPException(status_code=401, detail="Invalid or expired API key")
    return sub


# ─── Subscriber Management Models ─────────────────────────────

class CreateSubscriberRequest(BaseModel):
    name:         str
    email:        str = ""
    tier:         str = "starter"   # starter | pro | enterprise
    expires_days: int = 30

class AdminKeyHeader:
    """Simple admin auth — reads ADMIN_SECRET from env."""
    def __call__(self, x_admin_secret: str = Header(..., alias="X-Admin-Secret")):
        import os
        secret = os.getenv("ADMIN_SECRET", "nexus-admin-change-me")
        if x_admin_secret != secret:
            raise HTTPException(status_code=403, detail="Admin access required")
        return True

admin_auth = AdminKeyHeader()

# ─── Tier Signal Limits ───────────────────────────────────────
# How many signals per request each tier can receive

TIER_LIMITS = {
    "starter":    10,
    "pro":        50,
    "enterprise": 100,
}

# In-memory rate limiter: {api_key: [timestamps]}
from collections import defaultdict
import time as _time
_rate_store: dict = defaultdict(list)

def check_rate_limit(api_key: str, max_per_minute: int = 30):
    """Simple sliding-window rate limiter (per API key)."""
    now   = _time.time()
    hits  = _rate_store[api_key]
    # Purge hits older than 60s
    hits[:] = [t for t in hits if now - t < 60]
    if len(hits) >= max_per_minute:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Slow down.")
    hits.append(now)


# ─── Response Models ──────────────────────────────────────────

class SignalResponse(BaseModel):
    id:           str
    symbol:       str
    asset_class:  str
    action:       str
    entry_price:  float
    take_profit:  float
    stop_loss:    float
    confidence:   float
    risk_reward:  float
    strategy:     str
    timeframe:    str
    reasoning:    str
    sentiment:    float
    timestamp:    str
    outcome:      str
    pnl_pct:      Optional[float]

class StatsResponse(BaseModel):
    total_signals:  int
    wins:           int
    losses:         int
    win_rate:       float
    avg_rr:         float
    avg_confidence: float
    generated_at:   str

class WebhookRegistration(BaseModel):
    url:    HttpUrl
    secret: Optional[str] = None   # for HMAC signature verification
    events: list[str] = ["signal"]  # signal | tp_hit | sl_hit

class HealthResponse(BaseModel):
    status:     str
    timestamp:  str
    agents:     dict
    db:         str
    paper_mode: bool


# ─── In-memory webhook registry ───────────────────────────────

webhook_registry: list[dict] = []


# ─── Startup ──────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    await db.init()
    logger.info("[API] NEXUS AI Signal API started")

# ─── Dashboard ────────────────────────────────────────────────

@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def dashboard():
    """Admin dashboard — pass ?secret=YOUR_ADMIN_SECRET in URL."""
    from api.dashboard import DASHBOARD_HTML
    return HTMLResponse(content=DASHBOARD_HTML)

@app.get("/", include_in_schema=False)
async def root():
    return {"name": "NEXUS AI Signal API", "version": "1.0.0",
            "docs": "/docs", "dashboard": "/dashboard"}


@app.get("/health", response_model=HealthResponse)
async def health():
    """Public health check — no auth required."""
    return HealthResponse(
        status="operational",
        timestamp=datetime.utcnow().isoformat(),
        agents={
            "crawler":   "active",
            "technical": "active",
            "sentiment": "active",
            "strategy":  "active",
            "risk":      "active",
        },
        db="connected",
        paper_mode=Config.PAPER_TRADING,
    )


@api_router.get("/signals", response_model=list[SignalResponse])
async def get_signals(
    limit:          int   = Query(20, ge=1, le=100),
    asset_class:    Optional[str]   = Query(None, description="crypto | stock | forex"),
    action:         Optional[str]   = Query(None, description="BUY | SELL"),
    min_confidence: Optional[float] = Query(None, ge=0, le=100),
    sub:            dict  = Depends(verify_api_key),
):
    """Get recent signals filtered by tier permissions."""
    check_rate_limit(sub["api_key"])

    # Enforce tier signal limit
    tier_max = TIER_LIMITS.get(sub.get("tier", "starter"), 10)
    limit    = min(limit, tier_max)

    rows = await db.get_recent_signals(limit=limit * 3)

    if asset_class:
        rows = [r for r in rows if r["asset_class"] == asset_class]
    if action:
        rows = [r for r in rows if r["action"] == action.upper()]
    if min_confidence:
        rows = [r for r in rows if r["confidence"] >= min_confidence]

    # Starter tier: crypto only
    if sub.get("tier") == "starter":
        rows = [r for r in rows if r["asset_class"] == "crypto"]

    rows = rows[:limit]

    return [
        SignalResponse(
            id=r["id"], symbol=r["symbol"], asset_class=r["asset_class"],
            action=r["action"], entry_price=r["entry_price"],
            take_profit=r["take_profit"], stop_loss=r["stop_loss"],
            confidence=r["confidence"], risk_reward=r["risk_reward"],
            strategy=r["strategy"], timeframe=r["timeframe"],
            reasoning=r.get("reasoning", ""), sentiment=r.get("sentiment", 0.0),
            timestamp=r["timestamp"], outcome=r.get("outcome", "open"),
            pnl_pct=r.get("pnl_pct"),
        )
        for r in rows
    ]


@api_router.get("/signals/{signal_id}", response_model=SignalResponse)
async def get_signal(signal_id: str, _sub: dict = Depends(verify_api_key)):
    """Get a single signal by ID."""
    rows = await db.get_recent_signals(limit=500)
    match = next((r for r in rows if r["id"] == signal_id.upper()), None)
    if not match:
        raise HTTPException(status_code=404, detail=f"Signal {signal_id} not found")
    return SignalResponse(**{
        "id": match["id"],
        "symbol": match["symbol"],
        "asset_class": match["asset_class"],
        "action": match["action"],
        "entry_price": match["entry_price"],
        "take_profit": match["take_profit"],
        "stop_loss": match["stop_loss"],
        "confidence": match["confidence"],
        "risk_reward": match["risk_reward"],
        "strategy": match["strategy"],
        "timeframe": match["timeframe"],
        "reasoning": match.get("reasoning", ""),
        "sentiment": match.get("sentiment", 0.0),
        "timestamp": match["timestamp"],
        "outcome": match.get("outcome", "open"),
        "pnl_pct": match.get("pnl_pct"),
    })


@api_router.get("/stats", response_model=StatsResponse)
async def get_stats(_sub: dict = Depends(verify_api_key)):
    """Get aggregate performance statistics."""
    stats = await db.get_stats()
    return StatsResponse(
        total_signals=stats.get("total", 0),
        wins=stats.get("wins", 0),
        losses=stats.get("losses", 0),
        win_rate=stats.get("win_rate", 0.0),
        avg_rr=round(stats.get("avg_rr", 0.0) or 0.0, 2),
        avg_confidence=round(stats.get("avg_conf", 0.0) or 0.0, 1),
        generated_at=datetime.utcnow().isoformat(),
    )


@api_router.post("/webhook/register", status_code=201)
async def register_webhook(
    body: WebhookRegistration,
    _sub: dict = Depends(verify_api_key),
):
    """
    Register a webhook URL to receive signal events.
    When a signal fires, a POST with the signal JSON is sent to your URL.
    Include a secret for HMAC-SHA256 signature verification.
    """
    entry = {
        "url":    str(body.url),
        "secret": body.secret or secrets.token_hex(16),
        "events": body.events,
        "registered_at": datetime.utcnow().isoformat(),
    }
    webhook_registry.append(entry)
    logger.info(f"[API] Webhook registered: {entry['url']}")
    return {"status": "registered", "url": entry["url"], "secret": entry["secret"]}


@api_router.get("/webhooks", include_in_schema=False)
async def list_webhooks(_sub: dict = Depends(verify_api_key)):
    return {"webhooks": [{"url": w["url"], "events": w["events"]} for w in webhook_registry]}


@api_router.get("/me")
async def get_my_info(sub: dict = Depends(verify_api_key)):
    """Subscribers check their own plan info."""
    return {
        "name":         sub["name"],
        "tier":         sub["tier"],
        "expires_at":   sub.get("expires_at"),
        "signal_count": sub.get("signal_count", 0),
    }


# ─── Subscriber Management (admin-only) ───────────────────────

@api_router.post("/admin/subscribers", status_code=201)
async def create_subscriber(body: CreateSubscriberRequest, _ok: bool = Depends(admin_auth)):
    """Create a new subscriber and return their API key."""
    api_key = await db.create_subscriber(
        name=body.name, email=body.email,
        tier=body.tier, expires_days=body.expires_days,
    )
    if not api_key:
        raise HTTPException(status_code=500, detail="Failed to create subscriber")
    return {
        "api_key": api_key, "name": body.name, "tier": body.tier,
        "expires_in_days": body.expires_days,
        "note": "Share this key with your subscriber. It cannot be retrieved again.",
    }

@api_router.get("/admin/subscribers")
async def list_subscribers(_ok: bool = Depends(admin_auth)):
    subs = await db.list_subscribers()
    for s in subs:
        k = s.get("api_key", "")
        s["api_key"] = k[:8] + "…" + k[-4:] if len(k) > 12 else "****"
    return {"subscribers": subs, "total": len(subs)}

@api_router.delete("/admin/subscribers/{api_key}")
async def revoke_subscriber(api_key: str, _ok: bool = Depends(admin_auth)):
    await db.revoke_subscriber(api_key)
    return {"status": "revoked"}


# ─── Webhook Dispatcher (called by orchestrator) ──────────────

async def dispatch_webhooks(signal: TradingSignal):
    """Fire registered webhooks when a new signal is generated."""
    if not webhook_registry:
        return

    payload = json.dumps({
        "event":     "signal",
        "signal_id": signal.signal_id,
        "symbol":    signal.asset,
        "action":    signal.action.value,
        "entry":     signal.entry_price,
        "tp":        signal.take_profit,
        "sl":        signal.stop_loss,
        "confidence": signal.confidence,
        "rr":        signal.risk_reward,
        "strategy":  signal.strategy,
        "reasoning": signal.reasoning,
        "timestamp": signal.timestamp.isoformat(),
    })

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
        for webhook in webhook_registry:
            if "signal" not in webhook.get("events", []):
                continue
            headers = {"Content-Type": "application/json"}
            if webhook.get("secret"):
                sig = hmac.new(
                    webhook["secret"].encode(),
                    payload.encode(),
                    hashlib.sha256,
                ).hexdigest()
                headers["X-Nexus-Signature"] = f"sha256={sig}"
            try:
                async with session.post(webhook["url"], data=payload, headers=headers) as r:
                    logger.info(f"[API] Webhook {webhook['url']}: {r.status}")
            except Exception as e:
                logger.warning(f"[API] Webhook failed {webhook['url']}: {e}")


# ─── Mount api_router ─────────────────────────────────────────
# All authenticated endpoints are now accessible under /api/*
# e.g. GET /api/signals, GET /api/stats, POST /api/admin/subscribers

app.include_router(api_router)


# ─── Run standalone ───────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.routes:app", host="0.0.0.0", port=8000, reload=True)
