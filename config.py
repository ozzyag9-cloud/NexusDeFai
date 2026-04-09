"""
NEXUS AI - Core Configuration & Shared Models
Centralizes all settings and data structures used across agents.
"""

import os
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime
from enum import Enum
from dotenv import load_dotenv

load_dotenv()


# ─────────────────────────────────────────────
# ENUMS
# ─────────────────────────────────────────────

class SignalAction(str, Enum):
    BUY  = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"

class AssetClass(str, Enum):
    CRYPTO = "crypto"
    STOCK  = "stock"
    FOREX  = "forex"

class TimeFrame(str, Enum):
    M15  = "15m"
    H1   = "1h"
    H4   = "4h"
    D1   = "1d"


# ─────────────────────────────────────────────
# SIGNAL MODEL
# ─────────────────────────────────────────────

@dataclass
class TradingSignal:
    """The core output of the entire agent system."""
    asset:          str
    asset_class:    AssetClass
    action:         SignalAction
    entry_price:    float
    take_profit:    float
    stop_loss:      float
    confidence:     float          # 0–100
    risk_reward:    float
    strategy:       str
    timeframe:      TimeFrame
    reasoning:      str
    sentiment_score: float = 0.0   # -1 bearish → +1 bullish
    timestamp:      datetime = field(default_factory=datetime.utcnow)
    signal_id:      str = ""

    def __post_init__(self):
        if not self.signal_id:
            import hashlib
            raw = f"{self.asset}{self.timestamp.isoformat()}{self.action}"
            self.signal_id = hashlib.md5(raw.encode()).hexdigest()[:8].upper()

    @property
    def emoji(self) -> str:
        return {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}[self.action.value]

    @property
    def pnl_potential_pct(self) -> float:
        if self.action == SignalAction.BUY:
            return round((self.take_profit - self.entry_price) / self.entry_price * 100, 2)
        elif self.action == SignalAction.SELL:
            return round((self.entry_price - self.take_profit) / self.entry_price * 100, 2)
        return 0.0

    def to_telegram_message(self) -> str:
        ac_emoji = {"crypto": "🪙", "stock": "📈", "forex": "💱"}[self.asset_class.value]
        return (
            f"{self.emoji} *{self.action.value} SIGNAL* {ac_emoji}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"*Asset:* `{self.asset}`\n"
            f"*Entry:* `${self.entry_price:,.4f}`\n"
            f"*Take Profit:* `${self.take_profit:,.4f}` *(+{self.pnl_potential_pct:.1f}%)*\n"
            f"*Stop Loss:* `${self.stop_loss:,.4f}`\n"
            f"*R:R Ratio:* `{self.risk_reward:.1f}:1`\n"
            f"*Confidence:* `{self.confidence:.0f}%`\n"
            f"*Strategy:* `{self.strategy}`\n"
            f"*Timeframe:* `{self.timeframe.value}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"*Analysis:* _{self.reasoning}_\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 `#{self.signal_id}` | ⏰ `{self.timestamp.strftime('%H:%M UTC')}`\n"
            f"\n⚠️ _Always manage your risk. Never risk more than 1-2% per trade._"
        )


# ─────────────────────────────────────────────
# SYSTEM CONFIG
# ─────────────────────────────────────────────

class Config:
    # Telegram
    TELEGRAM_BOT_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHANNEL_ID  = os.getenv("TELEGRAM_CHANNEL_ID", "")
    TELEGRAM_ADMIN_ID    = int(os.getenv("TELEGRAM_ADMIN_ID", "0"))

    # Anthropic
    ANTHROPIC_API_KEY    = os.getenv("ANTHROPIC_API_KEY", "")

    # Risk
    RISK_PER_TRADE       = float(os.getenv("RISK_PER_TRADE", "0.01"))
    ACCOUNT_BALANCE      = float(os.getenv("ACCOUNT_BALANCE", "10000"))
    MIN_CONFIDENCE       = float(os.getenv("MIN_CONFIDENCE", "65"))

    # Scheduling
    SIGNAL_INTERVAL_MINS = int(os.getenv("SIGNAL_INTERVAL_MINS", "15"))
    PAPER_TRADING        = os.getenv("PAPER_TRADING", "true").lower() == "true"

    # Watchlists
    CRYPTO_WATCHLIST = os.getenv(
        "CRYPTO_WATCHLIST", "BTC-USD,ETH-USD,SOL-USD,BNB-USD"
    ).split(",")
    STOCKS_WATCHLIST = os.getenv(
        "STOCKS_WATCHLIST", "NVDA,AAPL,TSLA,SPY"
    ).split(",")
    FOREX_WATCHLIST = os.getenv(
        "FOREX_WATCHLIST", "EURUSD=X,GBPUSD=X,USDJPY=X"
    ).split(",")

    @classmethod
    def all_symbols(cls) -> list:
        return cls.CRYPTO_WATCHLIST + cls.STOCKS_WATCHLIST + cls.FOREX_WATCHLIST

    @classmethod
    def classify(cls, symbol: str) -> AssetClass:
        if symbol in cls.CRYPTO_WATCHLIST:
            return AssetClass.CRYPTO
        elif symbol in cls.STOCKS_WATCHLIST:
            return AssetClass.STOCK
        else:
            return AssetClass.FOREX
