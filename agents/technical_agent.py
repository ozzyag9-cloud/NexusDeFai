"""
NEXUS AI - Agent 2: Technical Analysis Agent
Computes 20+ indicators on OHLCV data.
Returns a structured indicator dict + a numeric bias score per timeframe.
"""

import pandas as pd
import numpy as np
import pandas_ta as ta
from loguru import logger
from dataclasses import dataclass
from typing import Optional


@dataclass
class IndicatorSet:
    """All computed indicators for one symbol/timeframe."""
    symbol:     str
    timeframe:  str

    # Trend
    ema_20:     Optional[float] = None
    ema_50:     Optional[float] = None
    ema_200:    Optional[float] = None
    sma_20:     Optional[float] = None

    # Momentum
    rsi:        Optional[float] = None
    macd:       Optional[float] = None
    macd_signal:Optional[float] = None
    macd_hist:  Optional[float] = None
    stoch_k:    Optional[float] = None
    stoch_d:    Optional[float] = None

    # Volatility
    atr:        Optional[float] = None
    atr_pct:    Optional[float] = None
    bb_upper:   Optional[float] = None
    bb_middle:  Optional[float] = None
    bb_lower:   Optional[float] = None
    bb_width:   Optional[float] = None
    bb_pct_b:   Optional[float] = None

    # Volume
    obv:        Optional[float] = None
    vwap:       Optional[float] = None
    volume_sma: Optional[float] = None
    volume_ratio: Optional[float] = None   # current / sma

    # Support / Resistance
    pivot:      Optional[float] = None
    r1:         Optional[float] = None
    r2:         Optional[float] = None
    s1:         Optional[float] = None
    s2:         Optional[float] = None

    # Derived
    trend_bias: Optional[float] = None   # -100 bearish → +100 bullish
    close:      Optional[float] = None


class TechnicalAgent:
    """
    Agent 2: Processes OHLCV DataFrames and outputs IndicatorSets.
    """

    def __init__(self):
        self.name = "TechnicalAgent"

    def compute(self, symbol: str, df: pd.DataFrame, timeframe: str) -> Optional[IndicatorSet]:
        """
        Main entry: compute all indicators on df.
        Returns populated IndicatorSet.
        """
        if df is None or len(df) < 50:
            logger.warning(f"[{self.name}] {symbol}/{timeframe}: insufficient data ({len(df) if df is not None else 0} rows)")
            return None

        ind = IndicatorSet(symbol=symbol, timeframe=timeframe)
        close = df["Close"]
        high  = df["High"]
        low   = df["Low"]
        vol   = df["Volume"]

        try:
            # ── Trend: EMAs & SMAs ────────────────────────────
            ind.ema_20  = float(ta.ema(close, length=20).iloc[-1])
            ind.ema_50  = float(ta.ema(close, length=50).iloc[-1])
            ind.ema_200 = float(ta.ema(close, length=200).iloc[-1]) if len(df) >= 200 else None
            ind.sma_20  = float(ta.sma(close, length=20).iloc[-1])

            # ── Momentum ──────────────────────────────────────
            rsi_s = ta.rsi(close, length=14)
            ind.rsi = float(rsi_s.iloc[-1]) if rsi_s is not None else None

            macd_df = ta.macd(close, fast=12, slow=26, signal=9)
            if macd_df is not None and not macd_df.empty:
                ind.macd        = float(macd_df.iloc[-1, 0])
                ind.macd_signal = float(macd_df.iloc[-1, 2])
                ind.macd_hist   = float(macd_df.iloc[-1, 1])

            stoch_df = ta.stoch(high, low, close, k=14, d=3)
            if stoch_df is not None and not stoch_df.empty:
                ind.stoch_k = float(stoch_df.iloc[-1, 0])
                ind.stoch_d = float(stoch_df.iloc[-1, 1])

            # ── Volatility: ATR & Bollinger Bands ─────────────
            atr_s = ta.atr(high, low, close, length=14)
            if atr_s is not None:
                ind.atr     = float(atr_s.iloc[-1])
                ind.atr_pct = ind.atr / float(close.iloc[-1]) * 100

            bb_df = ta.bbands(close, length=20, std=2)
            if bb_df is not None and not bb_df.empty:
                ind.bb_lower  = float(bb_df.iloc[-1, 0])
                ind.bb_middle = float(bb_df.iloc[-1, 1])
                ind.bb_upper  = float(bb_df.iloc[-1, 2])
                ind.bb_width  = float(bb_df.iloc[-1, 3]) if bb_df.shape[1] > 3 else None
                ind.bb_pct_b  = float(bb_df.iloc[-1, 4]) if bb_df.shape[1] > 4 else None

            # ── Volume ────────────────────────────────────────
            obv_s = ta.obv(close, vol)
            if obv_s is not None:
                ind.obv = float(obv_s.iloc[-1])

            if len(df) >= 20:
                ind.volume_sma   = float(vol.rolling(20).mean().iloc[-1])
                ind.volume_ratio = float(vol.iloc[-1]) / ind.volume_sma if ind.volume_sma else 1.0

            # VWAP (intraday timeframes)
            if timeframe in ("15m", "1h"):
                vwap_s = ta.vwap(high, low, close, vol)
                if vwap_s is not None:
                    ind.vwap = float(vwap_s.iloc[-1])

            # ── Pivot Points (Classic) ─────────────────────────
            prev_h = float(high.iloc[-2])
            prev_l = float(low.iloc[-2])
            prev_c = float(close.iloc[-2])
            ind.pivot = (prev_h + prev_l + prev_c) / 3
            ind.r1 = 2 * ind.pivot - prev_l
            ind.r2 = ind.pivot + (prev_h - prev_l)
            ind.s1 = 2 * ind.pivot - prev_h
            ind.s2 = ind.pivot - (prev_h - prev_l)

            # ── Current Close ─────────────────────────────────
            ind.close = float(close.iloc[-1])

            # ── Derived: Trend Bias Score (-100 → +100) ───────
            ind.trend_bias = self._compute_bias(ind)

        except Exception as e:
            logger.error(f"[{self.name}] compute({symbol}/{timeframe}): {e}")

        return ind

    def _compute_bias(self, ind: IndicatorSet) -> float:
        """
        Weighted scoring system → bias in [-100, +100].
        Each condition contributes a weighted vote.
        """
        score = 0.0
        weights = 0.0

        c = ind.close or 1.0

        # EMA alignment (strong trend signal)
        if ind.ema_20 and ind.ema_50:
            w = 20.0
            score += w if c > ind.ema_20 > ind.ema_50 else -w
            weights += w

        if ind.ema_200:
            w = 15.0
            score += w if c > ind.ema_200 else -w
            weights += w

        # RSI
        if ind.rsi is not None:
            w = 15.0
            if ind.rsi > 55:
                score += w * min((ind.rsi - 55) / 25, 1.0)
            elif ind.rsi < 45:
                score -= w * min((45 - ind.rsi) / 25, 1.0)
            weights += w

        # MACD histogram momentum
        if ind.macd_hist is not None:
            w = 15.0
            score += w if ind.macd_hist > 0 else -w
            weights += w

        # Bollinger Band position
        if ind.bb_pct_b is not None:
            w = 10.0
            if ind.bb_pct_b > 0.6:
                score += w * (ind.bb_pct_b - 0.5) * 2
            elif ind.bb_pct_b < 0.4:
                score -= w * (0.5 - ind.bb_pct_b) * 2
            weights += w

        # Stochastic
        if ind.stoch_k is not None and ind.stoch_d is not None:
            w = 10.0
            if ind.stoch_k > 50 and ind.stoch_k > ind.stoch_d:
                score += w
            elif ind.stoch_k < 50 and ind.stoch_k < ind.stoch_d:
                score -= w
            weights += w

        # Volume confirmation
        if ind.volume_ratio is not None:
            w = 5.0
            if ind.volume_ratio > 1.5:  # volume spike confirms direction
                # already accounted in bias direction; add small bonus
                score += w * (1 if score > 0 else -1)
            weights += w

        return round((score / weights * 100) if weights > 0 else 0, 1)

    def compute_all_timeframes(
        self, symbol: str, frames: dict
    ) -> dict[str, IndicatorSet]:
        """Compute indicators across all available timeframes."""
        result = {}
        for tf, df in frames.items():
            ind = self.compute(symbol, df, tf)
            if ind:
                result[tf] = ind
                logger.info(
                    f"[{self.name}] {symbol}/{tf}: RSI={ind.rsi:.1f} "
                    f"bias={ind.trend_bias:+.0f}"
                )
        return result

    def get_atr_levels(
        self,
        ind: IndicatorSet,
        action: str,
        atr_tp_mult: float = 2.0,
        atr_sl_mult: float = 1.0
    ) -> tuple[float, float]:
        """
        Compute ATR-based TP and SL from the indicator set.
        Returns (take_profit, stop_loss).
        """
        if not ind.close or not ind.atr:
            return (0.0, 0.0)

        if action == "BUY":
            tp = ind.close + ind.atr * atr_tp_mult
            sl = ind.close - ind.atr * atr_sl_mult
        else:
            tp = ind.close - ind.atr * atr_tp_mult
            sl = ind.close + ind.atr * atr_sl_mult

        return round(tp, 6), round(sl, 6)
