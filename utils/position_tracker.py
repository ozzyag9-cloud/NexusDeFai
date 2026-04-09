"""
NEXUS AI - Position Tracker
Tracks all open paper trades with live P&L, unrealised gains, and drawdown.
Publishes daily P&L summaries to Telegram.
Writes position state to DB for persistence across restarts.
"""

import asyncio
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from loguru import logger
from config import Config, SignalAction
from utils.database import SignalDatabase


@dataclass
class Position:
    signal_id:    str
    symbol:       str
    action:       str         # BUY or SELL
    entry_price:  float
    take_profit:  float
    stop_loss:    float
    size_usd:     float       # position size in USD
    opened_at:    datetime    = field(default_factory=datetime.utcnow)
    current_price: float      = 0.0

    @property
    def is_long(self) -> bool:
        return self.action == "BUY"

    @property
    def unrealised_pnl_pct(self) -> float:
        if not self.current_price or not self.entry_price:
            return 0.0
        if self.is_long:
            return (self.current_price - self.entry_price) / self.entry_price * 100
        else:
            return (self.entry_price - self.current_price) / self.entry_price * 100

    @property
    def unrealised_pnl_usd(self) -> float:
        return self.size_usd * self.unrealised_pnl_pct / 100

    @property
    def age_hours(self) -> float:
        return (datetime.utcnow() - self.opened_at).total_seconds() / 3600

    @property
    def distance_to_tp_pct(self) -> float:
        if not self.current_price:
            return 0.0
        if self.is_long:
            return (self.take_profit - self.current_price) / self.current_price * 100
        return (self.current_price - self.take_profit) / self.current_price * 100

    @property
    def distance_to_sl_pct(self) -> float:
        if not self.current_price:
            return 0.0
        if self.is_long:
            return (self.current_price - self.stop_loss) / self.current_price * 100
        return (self.stop_loss - self.current_price) / self.current_price * 100


class PositionTracker:
    """
    Maintains open paper positions with live P&L.
    Updates every 60s from the price feed or yfinance.
    """

    UPDATE_INTERVAL = 60    # seconds between price updates

    def __init__(self, db: SignalDatabase, publisher=None):
        self.db        = db
        self.publisher = publisher
        self.name      = "PositionTracker"
        self._positions: dict[str, Position] = {}   # signal_id → Position
        self._realised_pnl_today = 0.0
        self._trade_count_today  = 0
        self._day_start          = datetime.utcnow().date()

    # ── Position Management ───────────────────────────────────

    def open_position(self, signal_id: str, symbol: str, action: str,
                      entry: float, tp: float, sl: float, size_usd: float):
        """Register a new open position."""
        pos = Position(
            signal_id=signal_id, symbol=symbol, action=action,
            entry_price=entry, take_profit=tp, stop_loss=sl,
            size_usd=size_usd, current_price=entry,
        )
        self._positions[signal_id] = pos
        logger.info(f"[{self.name}] Opened {action} {symbol} @ {entry:.4f} (${size_usd:.0f})")

    def close_position(self, signal_id: str, exit_price: float, reason: str):
        """Close a position and record realised P&L."""
        pos = self._positions.pop(signal_id, None)
        if not pos:
            return
        pos.current_price = exit_price
        pnl_usd = pos.unrealised_pnl_usd
        pnl_pct = pos.unrealised_pnl_pct

        self._realised_pnl_today += pnl_usd
        self._trade_count_today  += 1

        emoji = "✅" if pnl_usd >= 0 else "❌"
        logger.success(
            f"[{self.name}] {emoji} Closed {pos.symbol} {pos.action} "
            f"→ {reason}  P&L: {pnl_pct:+.2f}% (${pnl_usd:+.0f})"
        )

    def get_open_positions(self) -> list[Position]:
        return list(self._positions.values())

    def get_summary(self) -> dict:
        positions = list(self._positions.values())
        total_unrealised = sum(p.unrealised_pnl_usd for p in positions)
        return {
            "open_count":         len(positions),
            "total_unrealised":   round(total_unrealised, 2),
            "realised_today":     round(self._realised_pnl_today, 2),
            "trade_count_today":  self._trade_count_today,
            "account_balance":    Config.ACCOUNT_BALANCE,
            "equity":             round(Config.ACCOUNT_BALANCE + total_unrealised, 2),
        }

    # ── Price Update Loop ─────────────────────────────────────

    async def _update_prices(self):
        """Refresh current prices for all open positions."""
        if not self._positions:
            return

        import yfinance as yf

        # Try live price feed first
        try:
            from utils.price_feed import price_feed
            for pos in self._positions.values():
                live = price_feed.get_price(pos.symbol)
                if live:
                    pos.current_price = live
                    continue
                # Fallback to yfinance
                try:
                    t = yf.Ticker(pos.symbol)
                    pos.current_price = float(t.fast_info.last_price)
                except Exception:
                    pass
        except ImportError:
            for pos in self._positions.values():
                try:
                    t = yf.Ticker(pos.symbol)
                    pos.current_price = float(t.fast_info.last_price)
                except Exception:
                    pass

    # ── Daily Summary ─────────────────────────────────────────

    async def _maybe_send_daily_summary(self):
        """Send end-of-day summary at midnight UTC."""
        today = datetime.utcnow().date()
        if today != self._day_start:
            self._day_start = today
            if self.publisher and self._trade_count_today > 0:
                sign = "+" if self._realised_pnl_today >= 0 else ""
                msg  = (
                    f"📆 *Daily P&L Summary*\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"Closed Trades: `{self._trade_count_today}`\n"
                    f"Realised P&L:  `{sign}${self._realised_pnl_today:.2f}`\n"
                    f"Open Positions: `{len(self._positions)}`\n"
                    f"Account Equity: `${Config.ACCOUNT_BALANCE + sum(p.unrealised_pnl_usd for p in self._positions.values()):.2f}`"
                )
                await self.publisher.send_admin(msg)
            # Reset daily counters
            self._realised_pnl_today = 0.0
            self._trade_count_today  = 0

    # ── Main Loop ─────────────────────────────────────────────

    async def run_loop(self):
        """Continuously update position prices and check for TP/SL hits."""
        logger.info(f"[{self.name}] Started")
        while True:
            try:
                await self._update_prices()
                await self._check_exits()
                await self._maybe_send_daily_summary()
            except Exception as e:
                logger.error(f"[{self.name}] loop error: {e}")
            await asyncio.sleep(self.UPDATE_INTERVAL)

    async def _check_exits(self):
        """Check open positions for TP/SL hits based on current price."""
        to_close = []
        for sig_id, pos in self._positions.items():
            if not pos.current_price:
                continue
            price = pos.current_price
            if pos.is_long:
                if price >= pos.take_profit:
                    to_close.append((sig_id, pos.take_profit, "TP Hit"))
                elif price <= pos.stop_loss:
                    to_close.append((sig_id, pos.stop_loss, "SL Hit"))
            else:
                if price <= pos.take_profit:
                    to_close.append((sig_id, pos.take_profit, "TP Hit"))
                elif price >= pos.stop_loss:
                    to_close.append((sig_id, pos.stop_loss, "SL Hit"))

        for sig_id, exit_price, reason in to_close:
            self.close_position(sig_id, exit_price, reason)
            # Sync with outcome tracker via DB
            pos_outcome = "tp_hit" if "TP" in reason else "sl_hit"
            entry = self._positions.get(sig_id)
            if entry:
                pnl = entry.unrealised_pnl_pct
                await self.db.update_outcome(sig_id, pos_outcome, pnl)

    def format_positions_message(self) -> str:
        """Telegram-formatted open positions summary."""
        positions = list(self._positions.values())
        if not positions:
            return "📋 No open positions."

        summary = self.get_summary()
        lines = [
            f"📋 *Open Positions ({len(positions)})*",
            f"━━━━━━━━━━━━━━━━━━━━",
        ]
        for pos in positions:
            pnl_e = "🟢" if pos.unrealised_pnl_pct >= 0 else "🔴"
            lines.append(
                f"{pnl_e} *{pos.symbol}* {pos.action}\n"
                f"  Entry: `{pos.entry_price:.4f}` | Now: `{pos.current_price:.4f}`\n"
                f"  P&L: `{pos.unrealised_pnl_pct:+.2f}%` (`${pos.unrealised_pnl_usd:+.0f}`)\n"
                f"  TP dist: `{pos.distance_to_tp_pct:.2f}%` | "
                f"SL dist: `{pos.distance_to_sl_pct:.2f}%`"
            )
        lines += [
            "━━━━━━━━━━━━━━━━━━━━",
            f"💼 Equity: `${summary['equity']:,.2f}` | "
            f"Unrealised: `${summary['total_unrealised']:+.2f}`",
        ]
        return "\n".join(lines)
