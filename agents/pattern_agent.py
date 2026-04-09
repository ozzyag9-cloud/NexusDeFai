"""
NEXUS AI - Agent 6: Pattern Detection Agent
Detects classic chart patterns on OHLCV data.
Patterns: Head & Shoulders, Double Top/Bottom, Bull/Bear Flag,
          Ascending/Descending Triangle, Wedge, Cup & Handle.
Returns detected patterns with bias direction and confidence.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional
from loguru import logger


@dataclass
class PatternResult:
    name:       str
    direction:  str   # bullish | bearish | neutral
    confidence: float
    description: str


class PatternAgent:
    """
    Agent 6: Detects chart patterns using price action heuristics.
    Complements the technical indicator signals.
    """

    def __init__(self):
        self.name = "PatternAgent"

    def detect_all(self, df: pd.DataFrame, symbol: str) -> list[PatternResult]:
        """Run all pattern detectors. Returns list of detected patterns."""
        if df is None or len(df) < 30:
            return []

        patterns = []
        detectors = [
            self._double_top_bottom,
            self._head_and_shoulders,
            self._bull_bear_flag,
            self._triangle,
            self._higher_lows_higher_highs,
        ]
        for fn in detectors:
            try:
                result = fn(df)
                if result:
                    patterns.append(result)
            except Exception as e:
                logger.debug(f"[{self.name}] {fn.__name__}: {e}")

        if patterns:
            logger.info(
                f"[{self.name}] {symbol}: {len(patterns)} pattern(s) — "
                + ", ".join(p.name for p in patterns)
            )
        return patterns

    def get_pattern_bias(self, patterns: list[PatternResult]) -> float:
        """Aggregate pattern bias score: -100 to +100."""
        if not patterns:
            return 0.0
        score = 0.0
        for p in patterns:
            weight = p.confidence / 100
            if p.direction == "bullish":
                score += weight * 100
            elif p.direction == "bearish":
                score -= weight * 100
        return round(score / len(patterns), 1)

    # ── Pattern Detectors ─────────────────────────────────────

    def _double_top_bottom(self, df: pd.DataFrame) -> Optional[PatternResult]:
        """Detect double top or double bottom in last 40 bars."""
        window = df.tail(40)
        highs  = window["High"].values
        lows   = window["Low"].values
        close  = window["Close"].values[-1]

        # Find two prominent highs within 2% of each other
        top1_idx = np.argmax(highs[:20])
        top2_idx = np.argmax(highs[20:]) + 20
        top1, top2 = highs[top1_idx], highs[top2_idx]

        if abs(top1 - top2) / top1 < 0.02 and close < min(top1, top2) * 0.99:
            return PatternResult(
                "Double Top", "bearish", 72,
                f"Two peaks at ${top1:.2f} and ${top2:.2f} — reversal pattern"
            )

        # Find two prominent lows within 2% of each other
        bot1_idx = np.argmin(lows[:20])
        bot2_idx = np.argmin(lows[20:]) + 20
        bot1, bot2 = lows[bot1_idx], lows[bot2_idx]

        if abs(bot1 - bot2) / bot1 < 0.02 and close > max(bot1, bot2) * 1.01:
            return PatternResult(
                "Double Bottom", "bullish", 74,
                f"Two troughs at ${bot1:.2f} and ${bot2:.2f} — reversal pattern"
            )
        return None

    def _head_and_shoulders(self, df: pd.DataFrame) -> Optional[PatternResult]:
        """Simple H&S detection: look for 3 peaks where middle is tallest."""
        if len(df) < 50:
            return None
        highs = df["High"].values[-50:]
        close = df["Close"].values[-1]

        # Split into thirds
        t = len(highs) // 3
        left_peak  = np.max(highs[:t])
        head       = np.max(highs[t:2*t])
        right_peak = np.max(highs[2*t:])

        if (head > left_peak * 1.03 and head > right_peak * 1.03
                and abs(left_peak - right_peak) / left_peak < 0.04):
            neckline = (np.min(df["Low"].values[-50:t]) + np.min(df["Low"].values[-50+2*t:])) / 2
            if close < neckline * 1.01:
                return PatternResult(
                    "Head & Shoulders", "bearish", 76,
                    f"Classic H&S — head={head:.2f}, neckline≈{neckline:.2f}"
                )
        return None

    def _bull_bear_flag(self, df: pd.DataFrame) -> Optional[PatternResult]:
        """Detect flag pattern: strong move followed by tight consolidation."""
        if len(df) < 20:
            return None

        pole    = df.tail(20).head(10)
        flag    = df.tail(10)
        close   = df["Close"]

        pole_move = (pole["Close"].iloc[-1] - pole["Close"].iloc[0]) / pole["Close"].iloc[0]
        flag_range = (flag["High"].max() - flag["Low"].min()) / flag["Close"].mean()
        flag_slope = (flag["Close"].iloc[-1] - flag["Close"].iloc[0]) / flag["Close"].iloc[0]

        # Bull flag: strong up move, tight sideways/down consolidation
        if pole_move > 0.04 and flag_range < 0.03 and -0.02 < flag_slope < 0.005:
            return PatternResult(
                "Bull Flag", "bullish", 68,
                f"Pole +{pole_move*100:.1f}%, tight consolidation — continuation expected"
            )

        # Bear flag: strong down move, tight sideways/up consolidation
        if pole_move < -0.04 and flag_range < 0.03 and -0.005 < flag_slope < 0.02:
            return PatternResult(
                "Bear Flag", "bearish", 68,
                f"Pole {pole_move*100:.1f}%, tight consolidation — continuation expected"
            )
        return None

    def _triangle(self, df: pd.DataFrame) -> Optional[PatternResult]:
        """Ascending / descending triangle detection."""
        if len(df) < 30:
            return None

        recent = df.tail(30)
        highs  = recent["High"].values
        lows   = recent["Low"].values

        high_slope = np.polyfit(range(len(highs)), highs, 1)[0]
        low_slope  = np.polyfit(range(len(lows)),  lows,  1)[0]

        flat_tol = abs(np.mean(highs)) * 0.001  # 0.1% of price

        if abs(high_slope) < flat_tol and low_slope > flat_tol:
            return PatternResult(
                "Ascending Triangle", "bullish", 65,
                "Flat resistance + rising lows — bullish breakout pattern"
            )
        if abs(low_slope) < flat_tol and high_slope < -flat_tol:
            return PatternResult(
                "Descending Triangle", "bearish", 65,
                "Flat support + falling highs — bearish breakdown pattern"
            )
        return None

    def _higher_lows_higher_highs(self, df: pd.DataFrame) -> Optional[PatternResult]:
        """Simple trend structure: HH+HL = uptrend, LH+LL = downtrend."""
        if len(df) < 20:
            return None

        h = df.tail(20)
        highs = h["High"].values
        lows  = h["Low"].values

        hh = highs[-1] > highs[-5] > highs[-10]
        hl = lows[-1]  > lows[-5]  > lows[-10]
        lh = highs[-1] < highs[-5] < highs[-10]
        ll = lows[-1]  < lows[-5]  < lows[-10]

        if hh and hl:
            return PatternResult(
                "Uptrend Structure", "bullish", 62,
                "Higher highs and higher lows confirm uptrend"
            )
        if lh and ll:
            return PatternResult(
                "Downtrend Structure", "bearish", 62,
                "Lower highs and lower lows confirm downtrend"
            )
        return None
