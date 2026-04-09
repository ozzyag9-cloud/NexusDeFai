"""
NEXUS AI - Signal Database
Async SQLite storage for all generated signals and backtest results.
"""

import json
import aiosqlite
from datetime import datetime
from loguru import logger
from config import TradingSignal, Config


DB_PATH = "nexus_ai.db"

CREATE_SIGNALS_SQL = """
CREATE TABLE IF NOT EXISTS signals (
    id          TEXT PRIMARY KEY,
    symbol      TEXT NOT NULL,
    asset_class TEXT NOT NULL,
    action      TEXT NOT NULL,
    entry_price REAL NOT NULL,
    take_profit REAL NOT NULL,
    stop_loss   REAL NOT NULL,
    confidence  REAL NOT NULL,
    risk_reward REAL NOT NULL,
    strategy    TEXT NOT NULL,
    timeframe   TEXT NOT NULL,
    reasoning   TEXT,
    sentiment   REAL DEFAULT 0,
    timestamp   TEXT NOT NULL,
    outcome     TEXT DEFAULT 'open',   -- open | tp_hit | sl_hit | expired
    pnl_pct     REAL DEFAULT NULL
)
"""

CREATE_STATS_SQL = """
CREATE TABLE IF NOT EXISTS daily_stats (
    date        TEXT PRIMARY KEY,
    total       INTEGER DEFAULT 0,
    wins        INTEGER DEFAULT 0,
    losses      INTEGER DEFAULT 0,
    win_rate    REAL DEFAULT 0,
    avg_rr      REAL DEFAULT 0
)
"""

CREATE_SUBSCRIBERS_SQL = """
CREATE TABLE IF NOT EXISTS subscribers (
    api_key     TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT,
    tier        TEXT DEFAULT 'starter',   -- starter | pro | enterprise
    active      INTEGER DEFAULT 1,
    created_at  TEXT NOT NULL,
    expires_at  TEXT,
    signal_count INTEGER DEFAULT 0
)
"""


class SignalDatabase:
    def __init__(self, path: str = DB_PATH):
        self.path = path

    async def init(self):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(CREATE_SIGNALS_SQL)
            await db.execute(CREATE_STATS_SQL)
            await db.execute(CREATE_SUBSCRIBERS_SQL)
            await db.commit()
        logger.info(f"[DB] Initialized at {self.path}")

    async def save_signal(self, signal: TradingSignal):
        try:
            async with aiosqlite.connect(self.path) as db:
                await db.execute("""
                    INSERT OR REPLACE INTO signals
                    (id, symbol, asset_class, action, entry_price, take_profit,
                     stop_loss, confidence, risk_reward, strategy, timeframe,
                     reasoning, sentiment, timestamp)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    signal.signal_id,
                    signal.asset,
                    signal.asset_class.value,
                    signal.action.value,
                    signal.entry_price,
                    signal.take_profit,
                    signal.stop_loss,
                    signal.confidence,
                    signal.risk_reward,
                    signal.strategy,
                    signal.timeframe.value,
                    signal.reasoning,
                    signal.sentiment_score,
                    signal.timestamp.isoformat(),
                ))
                await db.commit()
            logger.debug(f"[DB] Saved signal {signal.signal_id}")
        except Exception as e:
            logger.error(f"[DB] save_signal: {e}")

    async def get_recent_signals(self, limit: int = 20) -> list[dict]:
        try:
            async with aiosqlite.connect(self.path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT * FROM signals ORDER BY timestamp DESC LIMIT ?", (limit,)
                )
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"[DB] get_recent_signals: {e}")
            return []

    async def update_outcome(self, signal_id: str, outcome: str, pnl_pct: float):
        try:
            async with aiosqlite.connect(self.path) as db:
                await db.execute(
                    "UPDATE signals SET outcome=?, pnl_pct=? WHERE id=?",
                    (outcome, pnl_pct, signal_id)
                )
                await db.commit()
        except Exception as e:
            logger.error(f"[DB] update_outcome: {e}")

    async def get_stats(self) -> dict:
        """Return win rate and other performance stats."""
        try:
            async with aiosqlite.connect(self.path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN outcome='tp_hit' THEN 1 ELSE 0 END) as wins,
                        SUM(CASE WHEN outcome='sl_hit' THEN 1 ELSE 0 END) as losses,
                        AVG(risk_reward) as avg_rr,
                        AVG(confidence) as avg_conf
                    FROM signals WHERE outcome != 'open'
                """)
                row = await cursor.fetchone()
                d = dict(row)
                total = d["total"] or 0
                wins  = d["wins"]  or 0
                d["win_rate"] = round(wins / total * 100, 1) if total > 0 else 0.0
                return d
        except Exception as e:
            logger.error(f"[DB] get_stats: {e}")
            return {}

    # ── Subscriber / API Key Management ──────────────────────

    async def create_subscriber(
        self, name: str, email: str = "", tier: str = "starter",
        expires_days: int = 30
    ) -> str:
        """Create a new subscriber and return their API key."""
        import secrets
        from datetime import timedelta
        api_key    = f"nx-{secrets.token_urlsafe(24)}"
        created_at = datetime.utcnow().isoformat()
        expires_at = (datetime.utcnow() + timedelta(days=expires_days)).isoformat()
        try:
            async with aiosqlite.connect(self.path) as db:
                await db.execute("""
                    INSERT INTO subscribers (api_key, name, email, tier, active, created_at, expires_at)
                    VALUES (?,?,?,?,1,?,?)
                """, (api_key, name, email, tier, created_at, expires_at))
                await db.commit()
            logger.info(f"[DB] Subscriber created: {name} ({tier})")
            return api_key
        except Exception as e:
            logger.error(f"[DB] create_subscriber: {e}")
            return ""

    async def verify_api_key(self, api_key: str) -> dict | None:
        """Return subscriber dict if key is valid and active, else None."""
        try:
            async with aiosqlite.connect(self.path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT * FROM subscribers WHERE api_key=? AND active=1", (api_key,)
                )
                row = await cursor.fetchone()
                if not row:
                    return None
                sub = dict(row)
                # Check expiry
                if sub.get("expires_at"):
                    from datetime import datetime as dt
                    exp = dt.fromisoformat(sub["expires_at"])
                    if dt.utcnow() > exp:
                        return None
                return sub
        except Exception as e:
            logger.error(f"[DB] verify_api_key: {e}")
            return None

    async def list_subscribers(self) -> list[dict]:
        try:
            async with aiosqlite.connect(self.path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT api_key, name, email, tier, active, created_at, expires_at, signal_count "
                    "FROM subscribers ORDER BY created_at DESC"
                )
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"[DB] list_subscribers: {e}")
            return []

    async def revoke_subscriber(self, api_key: str):
        try:
            async with aiosqlite.connect(self.path) as db:
                await db.execute("UPDATE subscribers SET active=0 WHERE api_key=?", (api_key,))
                await db.commit()
        except Exception as e:
            logger.error(f"[DB] revoke_subscriber: {e}")
