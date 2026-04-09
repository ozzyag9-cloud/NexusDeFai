"""
NEXUS AI - Agent 5: Risk Management Agent
Computes dynamic Take Profit, Stop Loss, and position sizing.
Adapts multipliers per asset class and volatility regime.
"""

from loguru import logger
from config import AssetClass, SignalAction, Config
from agents.technical_agent import IndicatorSet


# ATR multipliers per asset class and regime
ATR_CONFIG = {
    AssetClass.CRYPTO: {
        "low_vol":  {"tp": 2.5, "sl": 1.2},
        "med_vol":  {"tp": 2.0, "sl": 1.0},
        "high_vol": {"tp": 1.5, "sl": 0.8},
    },
    AssetClass.STOCK: {
        "low_vol":  {"tp": 2.0, "sl": 1.0},
        "med_vol":  {"tp": 1.8, "sl": 0.9},
        "high_vol": {"tp": 1.5, "sl": 0.7},
    },
    AssetClass.FOREX: {
        "low_vol":  {"tp": 1.5, "sl": 0.8},
        "med_vol":  {"tp": 1.3, "sl": 0.7},
        "high_vol": {"tp": 1.0, "sl": 0.5},
    },
}


class RiskAgent:
    """
    Agent 5: Calculates TP, SL, R:R ratio, and position size.
    Uses ATR-based dynamic levels adapted to asset class + volatility.
    """

    def __init__(self):
        self.name = "RiskAgent"

    def _volatility_regime(self, ind: IndicatorSet) -> str:
        """Classify volatility from ATR%: low / med / high."""
        atr_pct = ind.atr_pct or 0
        if atr_pct < 1.0:
            return "low_vol"
        elif atr_pct < 3.0:
            return "med_vol"
        else:
            return "high_vol"

    def compute_levels(
        self,
        symbol: str,
        action: SignalAction,
        ind: IndicatorSet,
        asset_class: AssetClass,
        confidence: float = 70,
    ) -> dict:
        """
        Core risk calculation.
        Returns: {entry, take_profit, stop_loss, risk_reward, position_size_usd, atr_pct}
        """
        if not ind.close or not ind.atr:
            logger.warning(f"[{self.name}] {symbol}: missing close/ATR")
            return {}

        entry  = ind.close
        atr    = ind.atr
        regime = self._volatility_regime(ind)
        mults  = ATR_CONFIG.get(asset_class, ATR_CONFIG[AssetClass.CRYPTO])[regime]

        tp_mult = mults["tp"]
        sl_mult = mults["sl"]

        # Higher confidence → push TP a bit further
        if confidence >= 80:
            tp_mult *= 1.15
        elif confidence < 60:
            tp_mult *= 0.9

        # Compute raw levels
        if action == SignalAction.BUY:
            tp_raw = entry + atr * tp_mult
            sl_raw = entry - atr * sl_mult
        elif action == SignalAction.SELL:
            tp_raw = entry - atr * tp_mult
            sl_raw = entry + atr * sl_mult
        else:
            return {
                "entry": entry, "take_profit": entry, "stop_loss": entry,
                "risk_reward": 0.0, "position_size_usd": 0.0,
                "atr_pct": ind.atr_pct,
            }

        # Snap to nearest support/resistance if close
        tp, sl = self._snap_to_levels(ind, action, tp_raw, sl_raw, atr)

        # Risk : Reward
        tp_dist = abs(tp - entry)
        sl_dist = abs(sl - entry)
        rr = round(tp_dist / sl_dist, 2) if sl_dist > 0 else 0.0

        # Position sizing (fixed fractional risk)
        account  = Config.ACCOUNT_BALANCE
        risk_amt = account * Config.RISK_PER_TRADE
        pos_size_usd = round((risk_amt / sl_dist) * entry, 2) if sl_dist > 0 else 0.0
        pos_size_usd = min(pos_size_usd, account * 0.20)  # never exceed 20% in one trade

        dp = self._decimal_places(entry)

        result = {
            "entry":            round(entry, dp),
            "take_profit":      round(tp, dp),
            "stop_loss":        round(sl, dp),
            "risk_reward":      rr,
            "position_size_usd": pos_size_usd,
            "atr_pct":          round(ind.atr_pct or 0, 2),
            "regime":           regime,
            "tp_mult":          round(tp_mult, 2),
            "sl_mult":          round(sl_mult, 2),
        }

        logger.info(
            f"[{self.name}] {symbol} {action.value}: "
            f"entry={entry:.4f} TP={tp:.4f} SL={sl:.4f} "
            f"R:R={rr} regime={regime}"
        )
        return result

    def _snap_to_levels(
        self,
        ind: IndicatorSet,
        action: SignalAction,
        tp: float,
        sl: float,
        atr: float,
    ) -> tuple[float, float]:
        """
        If TP or SL is within 0.3 ATR of a pivot level, snap to it.
        This creates cleaner, more defensible levels.
        """
        levels = [v for v in [ind.r1, ind.r2, ind.s1, ind.s2, ind.pivot] if v]
        snap_tol = atr * 0.3

        for level in levels:
            if abs(tp - level) < snap_tol:
                tp = level
            if abs(sl - level) < snap_tol:
                sl = level
        return tp, sl

    def _decimal_places(self, price: float) -> int:
        """Return appropriate decimal precision for a price."""
        if price >= 1000:   return 2
        if price >= 10:     return 3
        if price >= 1:      return 4
        return 6

    def validate_signal(
        self, action: SignalAction, rr: float, confidence: float
    ) -> tuple[bool, str]:
        """
        Gate: should this signal be published?
        Returns (is_valid, rejection_reason).
        """
        if action == SignalAction.HOLD:
            return False, "HOLD signal — not published"
        if rr < 1.5:
            return False, f"R:R too low ({rr:.1f} < 1.5)"
        if confidence < Config.MIN_CONFIDENCE:
            return False, f"Confidence too low ({confidence:.0f}% < {Config.MIN_CONFIDENCE:.0f}%)"
        return True, ""
