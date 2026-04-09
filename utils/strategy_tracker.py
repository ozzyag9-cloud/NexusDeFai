"""
NEXUS AI - Strategy Performance Tracker
Analyses closed signals to score each strategy by win rate and avg P&L.
Feeds results back to the StrategyEngine to upweight winning strategies.
Also adds a daily summary table to the DB.
"""

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from loguru import logger
from utils.database import SignalDatabase


@dataclass
class StrategyStats:
    name:       str
    total:      int = 0
    wins:       int = 0
    losses:     int = 0
    total_pnl:  float = 0.0

    @property
    def win_rate(self) -> float:
        return round(self.wins / self.total * 100, 1) if self.total else 0.0

    @property
    def avg_pnl(self) -> float:
        return round(self.total_pnl / self.total, 3) if self.total else 0.0

    @property
    def score(self) -> float:
        """Composite score used for dynamic weight adjustment."""
        if self.total < 3:
            return 1.0   # not enough data — neutral weight
        wr = self.win_rate / 100
        return round(max(0.3, min(2.0, wr * 1.5 + self.avg_pnl * 0.1)), 3)


class StrategyPerformanceTracker:
    """
    Reads closed signals from DB, groups by strategy, computes stats,
    and returns a weight map that the StrategyEngine can apply.
    """

    def __init__(self, db: SignalDatabase):
        self.db   = db
        self.name = "StrategyTracker"
        self._cache: dict[str, StrategyStats] = {}
        self._cache_ts: datetime | None = None
        self._cache_ttl_mins = 30

    async def compute(self, lookback_days: int = 30) -> dict[str, StrategyStats]:
        """
        Compute per-strategy stats from the last N days of closed signals.
        Returns dict keyed by strategy name fragment.
        """
        # Use cache if fresh
        if (self._cache_ts and
                (datetime.utcnow() - self._cache_ts).total_seconds() < self._cache_ttl_mins * 60):
            return self._cache

        signals = await self.db.get_recent_signals(limit=500)
        cutoff  = datetime.utcnow() - timedelta(days=lookback_days)
        closed  = [
            s for s in signals
            if s.get("outcome") in ("tp_hit", "sl_hit")
            and s.get("pnl_pct") is not None
        ]

        stats: dict[str, StrategyStats] = defaultdict(lambda: StrategyStats(name=""))

        for sig in closed:
            # A signal may list multiple strategies: "EMA Cross + MACD Momentum"
            raw_strat = sig.get("strategy", "Unknown")
            parts     = [p.strip() for p in raw_strat.replace("+", "|").split("|")]

            for part in parts:
                if not part:
                    continue
                if part not in stats:
                    stats[part] = StrategyStats(name=part)
                s = stats[part]
                s.total     += 1
                s.total_pnl += sig.get("pnl_pct", 0.0)
                if sig["outcome"] == "tp_hit":
                    s.wins   += 1
                else:
                    s.losses += 1

        self._cache    = dict(stats)
        self._cache_ts = datetime.utcnow()

        if stats:
            logger.info(f"[{self.name}] Strategy scores:")
            for name, st in sorted(stats.items(), key=lambda x: -x[1].score):
                logger.info(
                    f"  {name:<25} WR={st.win_rate:.0f}%  "
                    f"avgPnL={st.avg_pnl:+.2f}%  "
                    f"score={st.score:.2f}  n={st.total}"
                )

        return dict(stats)

    async def get_weight_map(self) -> dict[str, float]:
        """
        Returns {strategy_name: weight_multiplier} for use in StrategyEngine.
        Score of 1.0 = neutral, >1.0 = upweight, <1.0 = downweight.
        """
        stats = await self.compute()
        return {name: st.score for name, st in stats.items()}

    def format_telegram_report(self, stats: dict[str, StrategyStats]) -> str:
        """Format strategy stats as a Telegram-ready message."""
        if not stats:
            return "📊 No closed signals yet to analyse strategies."

        lines = ["📊 *Strategy Performance Report*\n━━━━━━━━━━━━━━━━━━━━"]
        for name, st in sorted(stats.items(), key=lambda x: -x[1].score):
            if st.total < 2:
                continue
            bar   = "🟢" if st.win_rate >= 60 else "🟡" if st.win_rate >= 45 else "🔴"
            lines.append(
                f"{bar} *{name}*\n"
                f"  WR: `{st.win_rate:.0f}%` | AvgP&L: `{st.avg_pnl:+.2f}%` | "
                f"Trades: `{st.total}` | Score: `{st.score:.2f}`"
            )
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        return "\n".join(lines)
