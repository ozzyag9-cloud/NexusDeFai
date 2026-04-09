"""
NEXUS AI - Agent 4: Strategy Engine
Applies multiple trading strategies adapted per asset class.
Each strategy returns a weighted vote; ensemble produces the final signal.
"""

from dataclasses import dataclass
from typing import Optional
from loguru import logger
from config import AssetClass, SignalAction, TimeFrame
from agents.technical_agent import IndicatorSet


@dataclass
class StrategyVote:
    name:       str
    action:     SignalAction
    confidence: float   # 0–100
    weight:     float   # strategy weight in ensemble
    reason:     str


class StrategyEngine:
    """
    Agent 4: Multi-strategy ensemble.
    Runs all applicable strategies and returns a consensus signal.
    Supports dynamic weight adjustment from StrategyPerformanceTracker.
    """

    def __init__(self):
        self.name = "StrategyEngine"
        # Dynamic weights injected by StrategyPerformanceTracker.
        # Key = strategy name fragment, value = multiplier (default 1.0).
        self._dynamic_weights: dict[str, float] = {}

    def update_weights(self, weight_map: dict[str, float]):
        """Called by orchestrator after each StrategyPerformanceTracker.get_weight_map()."""
        self._dynamic_weights = weight_map
        logger.debug(f"[{self.name}] Dynamic weights updated: {weight_map}")

    def _effective_weight(self, base_weight: float, strategy_name: str) -> float:
        """Blend base weight with dynamic performance weight."""
        for key, dw in self._dynamic_weights.items():
            if key.lower() in strategy_name.lower():
                return round(base_weight * dw, 3)
        return base_weight

    # ──────────────────────────────────────────────────────────
    # Individual Strategies
    # ──────────────────────────────────────────────────────────

    def strategy_ema_crossover(self, ind: IndicatorSet) -> Optional[StrategyVote]:
        """Classic EMA 20/50 crossover with trend filter."""
        if not all([ind.ema_20, ind.ema_50, ind.close]):
            return None
        c = ind.close
        e20, e50 = ind.ema_20, ind.ema_50
        gap_pct = abs(e20 - e50) / e50 * 100

        if e20 > e50 and c > e20:
            conf = min(60 + gap_pct * 5, 90)
            return StrategyVote("EMA Cross", SignalAction.BUY, conf, 1.0,
                                f"EMA20 ({e20:.2f}) above EMA50 ({e50:.2f}), price above both")
        elif e20 < e50 and c < e20:
            conf = min(60 + gap_pct * 5, 90)
            return StrategyVote("EMA Cross", SignalAction.SELL, conf, 1.0,
                                f"EMA20 ({e20:.2f}) below EMA50 ({e50:.2f}), price below both")
        return StrategyVote("EMA Cross", SignalAction.HOLD, 50, 1.0, "EMAs mixed")

    def strategy_rsi_reversal(self, ind: IndicatorSet) -> Optional[StrategyVote]:
        """RSI oversold/overbought with BB confirmation."""
        if ind.rsi is None:
            return None
        rsi = ind.rsi
        pct_b = ind.bb_pct_b

        if rsi < 32:
            conf = 55 + (32 - rsi) * 2
            bb_bonus = 10 if pct_b is not None and pct_b < 0.1 else 0
            return StrategyVote("RSI Reversal", SignalAction.BUY, min(conf + bb_bonus, 88), 0.9,
                                f"RSI oversold at {rsi:.1f}" + (" + price below lower BB" if bb_bonus else ""))
        elif rsi > 68:
            conf = 55 + (rsi - 68) * 2
            bb_bonus = 10 if pct_b is not None and pct_b > 0.9 else 0
            return StrategyVote("RSI Reversal", SignalAction.SELL, min(conf + bb_bonus, 88), 0.9,
                                f"RSI overbought at {rsi:.1f}" + (" + price above upper BB" if bb_bonus else ""))
        return StrategyVote("RSI Reversal", SignalAction.HOLD, 40, 0.9, f"RSI neutral at {rsi:.1f}")

    def strategy_macd_momentum(self, ind: IndicatorSet) -> Optional[StrategyVote]:
        """MACD histogram momentum with crossover detection."""
        if ind.macd is None or ind.macd_signal is None or ind.macd_hist is None:
            return None
        hist = ind.macd_hist
        macd, sig = ind.macd, ind.macd_signal

        if macd > sig and hist > 0:
            conf = 55 + min(abs(hist) * 100, 25)
            return StrategyVote("MACD Momentum", SignalAction.BUY, conf, 1.1,
                                f"MACD above signal, histogram positive ({hist:.4f})")
        elif macd < sig and hist < 0:
            conf = 55 + min(abs(hist) * 100, 25)
            return StrategyVote("MACD Momentum", SignalAction.SELL, conf, 1.1,
                                f"MACD below signal, histogram negative ({hist:.4f})")
        return StrategyVote("MACD Momentum", SignalAction.HOLD, 45, 1.1, "MACD near crossover")

    def strategy_bollinger_squeeze(self, ind: IndicatorSet) -> Optional[StrategyVote]:
        """Bollinger Band squeeze breakout."""
        if not all([ind.bb_upper, ind.bb_lower, ind.close, ind.bb_width]):
            return None
        c = ind.close
        pct_b = ind.bb_pct_b
        width = ind.bb_width

        # Low width = squeeze = volatility incoming
        is_squeeze = width is not None and width < 0.05

        if c > ind.bb_upper:
            conf = 72 + (10 if is_squeeze else 0)
            return StrategyVote("BB Breakout", SignalAction.BUY, conf, 0.8,
                                f"Price above upper BB — upside breakout" + (" from squeeze" if is_squeeze else ""))
        elif c < ind.bb_lower:
            conf = 72 + (10 if is_squeeze else 0)
            return StrategyVote("BB Breakout", SignalAction.SELL, conf, 0.8,
                                f"Price below lower BB — downside breakout" + (" from squeeze" if is_squeeze else ""))
        return StrategyVote("BB Breakout", SignalAction.HOLD, 40, 0.8, "Price inside Bollinger Bands")

    def strategy_support_resistance(self, ind: IndicatorSet) -> Optional[StrategyVote]:
        """Pivot point support/resistance bounce."""
        if not all([ind.pivot, ind.r1, ind.s1, ind.close]):
            return None
        c = ind.close
        s1, r1 = ind.s1, ind.r1
        tol = ind.atr * 0.3 if ind.atr else abs(r1 - s1) * 0.1

        if abs(c - s1) < tol:
            return StrategyVote("S/R Bounce", SignalAction.BUY, 68, 0.7,
                                f"Price at S1 support ({s1:.4f}) — bounce expected")
        elif abs(c - r1) < tol:
            return StrategyVote("S/R Bounce", SignalAction.SELL, 68, 0.7,
                                f"Price at R1 resistance ({r1:.4f}) — rejection expected")
        elif c > r1:
            return StrategyVote("S/R Bounce", SignalAction.BUY, 62, 0.7,
                                f"Price broke above R1 ({r1:.4f}) — continuation")
        elif c < s1:
            return StrategyVote("S/R Bounce", SignalAction.SELL, 62, 0.7,
                                f"Price broke below S1 ({s1:.4f}) — continuation")
        return None

    def strategy_volume_trend(self, ind: IndicatorSet) -> Optional[StrategyVote]:
        """Volume-confirmed trend."""
        if ind.volume_ratio is None or ind.trend_bias is None:
            return None
        ratio = ind.volume_ratio
        bias  = ind.trend_bias

        if ratio > 1.5 and bias > 30:
            conf = 60 + min(ratio * 5, 20)
            return StrategyVote("Volume Trend", SignalAction.BUY, conf, 0.8,
                                f"High volume ({ratio:.1f}x avg) confirms bullish trend")
        elif ratio > 1.5 and bias < -30:
            conf = 60 + min(ratio * 5, 20)
            return StrategyVote("Volume Trend", SignalAction.SELL, conf, 0.8,
                                f"High volume ({ratio:.1f}x avg) confirms bearish trend")
        return None

    # ──────────────────────────────────────────────────────────
    # Asset-Class Strategy Selector
    # ──────────────────────────────────────────────────────────

    def _get_strategies_for(self, asset_class: AssetClass) -> list:
        """Return strategy methods weighted for the asset class."""
        base = [
            self.strategy_ema_crossover,
            self.strategy_rsi_reversal,
            self.strategy_macd_momentum,
            self.strategy_bollinger_squeeze,
            self.strategy_volume_trend,
        ]
        if asset_class in (AssetClass.CRYPTO, AssetClass.STOCK):
            base.append(self.strategy_support_resistance)
        return base

    # ──────────────────────────────────────────────────────────
    # Ensemble
    # ──────────────────────────────────────────────────────────

    def run_ensemble(
        self,
        symbol: str,
        ind: IndicatorSet,
        asset_class: AssetClass,
        sentiment_score: float = 0.0,
        higher_tf_bias: float = 0.0,
    ) -> dict:
        """
        Run all strategies → weighted vote → consensus signal.
        Returns: {action, confidence, strategy_name, reasoning, votes}
        """
        strategies = self._get_strategies_for(asset_class)
        votes: list[StrategyVote] = []

        for fn in strategies:
            v = fn(ind)
            if v:
                votes.append(v)

        if not votes:
            return {"action": SignalAction.HOLD, "confidence": 0, "strategy_name": "N/A",
                    "reasoning": "Insufficient data", "votes": []}

        # Weighted tally
        buy_score  = sum(v.confidence * self._effective_weight(v.weight, v.name) for v in votes if v.action == SignalAction.BUY)
        sell_score = sum(v.confidence * self._effective_weight(v.weight, v.name) for v in votes if v.action == SignalAction.SELL)
        hold_score = sum(v.confidence * self._effective_weight(v.weight, v.name) for v in votes if v.action == SignalAction.HOLD)
        total_w    = sum(self._effective_weight(v.weight, v.name) for v in votes)

        # Sentiment modifier (max ±8 points)
        sentiment_mod = sentiment_score * 8
        buy_score  += sentiment_mod if sentiment_mod > 0 else 0
        sell_score -= sentiment_mod if sentiment_mod < 0 else 0

        # Higher TF confirmation (max ±10 points)
        htf_mod = higher_tf_bias / 10
        buy_score  += htf_mod if htf_mod > 0 else 0
        sell_score -= htf_mod if htf_mod < 0 else 0

        # Determine action
        if buy_score > sell_score and buy_score > hold_score:
            action = SignalAction.BUY
            raw_conf = buy_score / total_w if total_w else 0
        elif sell_score > buy_score and sell_score > hold_score:
            action = SignalAction.SELL
            raw_conf = sell_score / total_w if total_w else 0
        else:
            action = SignalAction.HOLD
            raw_conf = 50.0

        confidence = round(min(raw_conf, 95), 1)

        # Best vote for strategy name
        action_votes = [v for v in votes if v.action == action]
        top_vote = max(action_votes, key=lambda v: v.confidence) if action_votes else votes[0]

        # Strategy names summary
        strategy_names = " + ".join(
            set(v.name for v in votes if v.action == action)
        ) or top_vote.name

        # Reasoning from top vote
        reasoning = top_vote.reason
        if len(action_votes) > 1:
            reasoning += f" (confirmed by {len(action_votes)} strategies)"

        logger.info(
            f"[{self.name}] {symbol}: {action.value} conf={confidence:.0f}% "
            f"buy={buy_score:.0f} sell={sell_score:.0f} [{strategy_names}]"
        )

        return {
            "action":        action,
            "confidence":    confidence,
            "strategy_name": strategy_names,
            "reasoning":     reasoning,
            "votes":         votes,
        }
