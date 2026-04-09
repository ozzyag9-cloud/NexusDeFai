"""
NEXUS AI - Outcome Tracker
Monitors open signals and automatically marks them as TP hit, SL hit, or expired.
Runs as a background task every 15 minutes alongside the main scheduler.
Sends Telegram notifications when outcomes are resolved.
"""

import asyncio
from datetime import datetime, timedelta
from loguru import logger
import yfinance as yf

from config import SignalAction
from utils.database import SignalDatabase


EXPIRY_HOURS = 72   # signals expire after 3 days if neither TP nor SL is hit


class OutcomeTracker:
    """
    Polls open signals, fetches current OHLC, and resolves outcomes.
    Publishes result notifications to Telegram.
    """

    def __init__(self, db: SignalDatabase, publisher=None):
        self.db        = db
        self.publisher = publisher   # TelegramPublisher or None
        self.name      = "OutcomeTracker"

    async def check_all_open(self):
        """Check every open signal against current price data."""
        signals = await self.db.get_recent_signals(limit=200)
        open_signals = [s for s in signals if s.get("outcome") == "open"]

        if not open_signals:
            return

        logger.info(f"[{self.name}] Checking {len(open_signals)} open signal(s)")

        for sig in open_signals:
            await self._check_signal(sig)

    async def _check_signal(self, sig: dict):
        """Evaluate one signal against current market data."""
        symbol    = sig["symbol"]
        action    = sig["action"]          # BUY or SELL
        entry     = sig["entry_price"]
        tp        = sig["take_profit"]
        sl        = sig["stop_loss"]
        ts_str    = sig["timestamp"]

        # Parse timestamp
        try:
            ts = datetime.fromisoformat(ts_str)
        except Exception:
            return

        # Check expiry
        age_hours = (datetime.utcnow() - ts).total_seconds() / 3600
        if age_hours > EXPIRY_HOURS:
            await self.db.update_outcome(sig["id"], "expired", 0.0)
            logger.info(f"[{self.name}] {symbol} #{sig['id']} expired after {age_hours:.0f}h")
            return

        # Fetch recent candles (last 2 days at 1h interval)
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="2d", interval="1h")
            if df.empty:
                return

            # Only look at candles AFTER signal timestamp
            df.index = df.index.tz_localize(None) if df.index.tz else df.index
            ts_naive = ts.replace(tzinfo=None)
            df = df[df.index > ts_naive]

            if df.empty:
                return

        except Exception as e:
            logger.warning(f"[{self.name}] fetch {symbol}: {e}")
            return

        # Check each candle for TP/SL hit
        outcome = None
        exit_price = None

        for _, row in df.iterrows():
            high = row["High"]
            low  = row["Low"]

            if action == "BUY":
                hit_tp = high >= tp
                hit_sl = low  <= sl
            else:  # SELL
                hit_tp = low  <= tp
                hit_sl = high >= sl

            # Conservative: if both hit in same bar, SL wins
            if hit_sl:
                outcome    = "sl_hit"
                exit_price = sl
                break
            elif hit_tp:
                outcome    = "tp_hit"
                exit_price = tp
                break

        if outcome:
            # Calculate P&L %
            if action == "BUY":
                pnl_pct = (exit_price - entry) / entry * 100
            else:
                pnl_pct = (entry - exit_price) / entry * 100

            pnl_pct = round(pnl_pct, 3)
            await self.db.update_outcome(sig["id"], outcome, pnl_pct)

            emoji   = "✅" if outcome == "tp_hit" else "❌"
            verdict = "TAKE PROFIT HIT" if outcome == "tp_hit" else "STOP LOSS HIT"
            logger.success(
                f"[{self.name}] {emoji} {symbol} #{sig['id']} → "
                f"{verdict}  P&L: {pnl_pct:+.2f}%"
            )

            # Notify Telegram
            if self.publisher:
                await self._notify_outcome(sig, outcome, exit_price, pnl_pct)

    async def _notify_outcome(
        self,
        sig: dict,
        outcome: str,
        exit_price: float,
        pnl_pct: float,
    ):
        """Send outcome notification to Telegram channel."""
        emoji   = "✅" if outcome == "tp_hit" else "❌"
        verdict = "TAKE PROFIT HIT 🎯" if outcome == "tp_hit" else "STOP LOSS HIT 🛑"
        action_emoji = "🟢" if sig["action"] == "BUY" else "🔴"
        pnl_sign = "+" if pnl_pct >= 0 else ""

        msg = (
            f"{emoji} *SIGNAL CLOSED — {verdict}*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{action_emoji} *{sig['symbol']}* {sig['action']}\n"
            f"*Entry:* `${sig['entry_price']:,.4f}`\n"
            f"*Exit:* `${exit_price:,.4f}`\n"
            f"*Result:* `{pnl_sign}{pnl_pct:.2f}%`\n"
            f"*R:R Achieved:* `{sig['risk_reward']:.1f}:1`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 `#{sig['id']}` | _{sig['strategy']}_"
        )

        try:
            await self.publisher.publish_text(msg)
        except Exception as e:
            logger.warning(f"[{self.name}] notify failed: {e}")

    async def run_loop(self, interval_minutes: int = 15):
        """Run the tracker continuously."""
        logger.info(f"[{self.name}] Starting (every {interval_minutes}m)")
        while True:
            try:
                await self.check_all_open()
            except Exception as e:
                logger.error(f"[{self.name}] loop error: {e}")
            await asyncio.sleep(interval_minutes * 60)
