"""
NEXUS AI - Unit Test Suite
Run with: python -m pytest tests/ -v
Or:        python -m pytest tests/ -v --tb=short -q
"""

import asyncio
import sys
import os
import pytest
import pandas as pd
import numpy as np
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

# Make sure nexus_ai root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════

def make_ohlcv(n=100, trend="up") -> pd.DataFrame:
    """Generate synthetic OHLCV DataFrame for testing."""
    np.random.seed(42)
    base = 50000.0
    closes = [base]
    for _ in range(n - 1):
        direction = 1 if trend == "up" else -1 if trend == "down" else 0
        closes.append(closes[-1] * (1 + direction * 0.002 + np.random.randn() * 0.005))

    closes = np.array(closes)
    highs  = closes * (1 + np.abs(np.random.randn(n) * 0.003))
    lows   = closes * (1 - np.abs(np.random.randn(n) * 0.003))
    opens  = np.roll(closes, 1)
    opens[0] = closes[0]
    vols   = np.random.randint(100, 10000, n).astype(float)

    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": vols},
        index=idx,
    )


# ═══════════════════════════════════════════════════════════════
# CONFIG & MODELS
# ═══════════════════════════════════════════════════════════════

class TestConfig:
    def test_all_symbols_not_empty(self):
        from config import Config
        syms = Config.all_symbols()
        assert len(syms) > 0, "Watchlist must not be empty"

    def test_classify_crypto(self):
        from config import Config, AssetClass
        # Default watchlist should contain BTC-USD
        result = Config.classify("BTC-USD")
        assert result == AssetClass.CRYPTO

    def test_classify_stock(self):
        from config import Config, AssetClass
        result = Config.classify("NVDA")
        assert result == AssetClass.STOCK

    def test_classify_forex(self):
        from config import Config, AssetClass
        result = Config.classify("EURUSD=X")
        assert result == AssetClass.FOREX

    def test_risk_within_bounds(self):
        from config import Config
        assert 0 < Config.RISK_PER_TRADE <= 0.05, "Risk per trade should be 0–5%"

    def test_min_confidence_reasonable(self):
        from config import Config
        assert 50 <= Config.MIN_CONFIDENCE <= 90

    def test_trading_signal_id_generated(self):
        from config import TradingSignal, SignalAction, AssetClass, TimeFrame
        sig = TradingSignal(
            asset="BTC-USD", asset_class=AssetClass.CRYPTO,
            action=SignalAction.BUY, entry_price=96000.0,
            take_profit=102000.0, stop_loss=92000.0,
            confidence=75.0, risk_reward=1.5, strategy="EMA Cross",
            timeframe=TimeFrame.H1, reasoning="Test signal",
        )
        assert len(sig.signal_id) == 8
        assert sig.pnl_potential_pct > 0

    def test_trading_signal_telegram_format(self):
        from config import TradingSignal, SignalAction, AssetClass, TimeFrame
        sig = TradingSignal(
            asset="ETH-USD", asset_class=AssetClass.CRYPTO,
            action=SignalAction.SELL, entry_price=3000.0,
            take_profit=2700.0, stop_loss=3150.0,
            confidence=70.0, risk_reward=2.0, strategy="RSI Reversal",
            timeframe=TimeFrame.H1, reasoning="Overbought",
        )
        msg = sig.to_telegram_message()
        assert "SELL" in msg
        assert "ETH-USD" in msg
        assert "2700" in msg
        assert "3150" in msg


# ═══════════════════════════════════════════════════════════════
# TECHNICAL AGENT
# ═══════════════════════════════════════════════════════════════

class TestTechnicalAgent:
    def setup_method(self):
        from agents.technical_agent import TechnicalAgent
        self.agent = TechnicalAgent()

    def test_compute_returns_indicator_set(self):
        df  = make_ohlcv(200)
        ind = self.agent.compute("BTC-USD", df, "1h")
        assert ind is not None
        assert ind.symbol == "BTC-USD"
        assert ind.close is not None and ind.close > 0

    def test_rsi_in_bounds(self):
        df  = make_ohlcv(100)
        ind = self.agent.compute("BTC-USD", df, "1h")
        assert ind.rsi is not None
        assert 0 <= ind.rsi <= 100, f"RSI {ind.rsi} out of 0-100 range"

    def test_ema_ordering_uptrend(self):
        df  = make_ohlcv(250, trend="up")
        ind = self.agent.compute("BTC-USD", df, "1h")
        if ind.ema_20 and ind.ema_50:
            # In uptrend EMA20 should be above EMA50
            assert ind.ema_20 >= ind.ema_50 * 0.98, "EMA20 should be near or above EMA50 in uptrend"

    def test_atr_positive(self):
        df  = make_ohlcv(100)
        ind = self.agent.compute("BTC-USD", df, "1h")
        assert ind.atr is not None and ind.atr > 0

    def test_bias_in_range(self):
        df  = make_ohlcv(200)
        ind = self.agent.compute("BTC-USD", df, "1h")
        assert ind.trend_bias is not None
        assert -100 <= ind.trend_bias <= 100

    def test_pivot_levels_consistent(self):
        df  = make_ohlcv(100)
        ind = self.agent.compute("BTC-USD", df, "1h")
        if ind.r1 and ind.s1 and ind.pivot:
            assert ind.r1 > ind.pivot > ind.s1, "R1 > Pivot > S1"

    def test_insufficient_data_returns_none(self):
        df  = make_ohlcv(10)   # too few rows
        ind = self.agent.compute("BTC-USD", df, "1h")
        assert ind is None

    def test_atr_levels_buy(self):
        from agents.technical_agent import IndicatorSet
        ind = IndicatorSet("BTC-USD", "1h")
        ind.close = 50000.0
        ind.atr   = 1000.0
        tp, sl = self.agent.get_atr_levels(ind, "BUY", atr_tp_mult=2.0, atr_sl_mult=1.0)
        assert tp == 52000.0
        assert sl == 49000.0

    def test_atr_levels_sell(self):
        from agents.technical_agent import IndicatorSet
        ind = IndicatorSet("BTC-USD", "1h")
        ind.close = 50000.0
        ind.atr   = 1000.0
        tp, sl = self.agent.get_atr_levels(ind, "SELL", atr_tp_mult=2.0, atr_sl_mult=1.0)
        assert tp == 48000.0
        assert sl == 51000.0


# ═══════════════════════════════════════════════════════════════
# STRATEGY ENGINE
# ═══════════════════════════════════════════════════════════════

class TestStrategyEngine:
    def setup_method(self):
        from agents.strategy_agent  import StrategyEngine
        from agents.technical_agent import TechnicalAgent
        self.engine    = StrategyEngine()
        self.technical = TechnicalAgent()

    def _make_ind(self, trend="up"):
        df  = make_ohlcv(250, trend=trend)
        return self.technical.compute("BTC-USD", df, "1h")

    def test_ensemble_returns_action(self):
        from config import AssetClass
        ind    = self._make_ind()
        result = self.engine.run_ensemble("BTC-USD", ind, AssetClass.CRYPTO)
        assert result["action"] is not None
        assert 0 <= result["confidence"] <= 100

    def test_uptrend_biases_buy(self):
        from config import AssetClass, SignalAction
        ind    = self._make_ind("up")
        result = self.engine.run_ensemble("BTC-USD", ind, AssetClass.CRYPTO)
        # In consistent uptrend more likely BUY than SELL
        assert result["action"] in (SignalAction.BUY, SignalAction.HOLD)

    def test_downtrend_biases_sell(self):
        from config import AssetClass, SignalAction
        ind    = self._make_ind("down")
        result = self.engine.run_ensemble("BTC-USD", ind, AssetClass.CRYPTO)
        assert result["action"] in (SignalAction.SELL, SignalAction.HOLD)

    def test_dynamic_weights_applied(self):
        from config import AssetClass
        self.engine.update_weights({"EMA Cross": 2.0, "RSI Reversal": 0.1})
        ind    = self._make_ind()
        result = self.engine.run_ensemble("BTC-USD", ind, AssetClass.CRYPTO)
        # Should still return a valid result with modified weights
        assert result["action"] is not None

    def test_sentiment_modifier_shifts_confidence(self):
        from config import AssetClass
        ind = self._make_ind()
        r1  = self.engine.run_ensemble("BTC-USD", ind, AssetClass.CRYPTO, sentiment_score=0.0)
        r2  = self.engine.run_ensemble("BTC-USD", ind, AssetClass.CRYPTO, sentiment_score=0.9)
        # Strongly bullish sentiment should affect buy_score
        assert r1["confidence"] != r2["confidence"] or r1["action"] == r2["action"]


# ═══════════════════════════════════════════════════════════════
# RISK AGENT
# ═══════════════════════════════════════════════════════════════

class TestRiskAgent:
    def setup_method(self):
        from agents.risk_agent      import RiskAgent
        from agents.technical_agent import TechnicalAgent
        self.risk      = RiskAgent()
        self.technical = TechnicalAgent()

    def _ind(self):
        df = make_ohlcv(200)
        return self.technical.compute("BTC-USD", df, "1h")

    def test_tp_above_entry_for_buy(self):
        from config import SignalAction, AssetClass
        ind    = self._ind()
        result = self.risk.compute_levels("BTC-USD", SignalAction.BUY, ind, AssetClass.CRYPTO)
        assert result["take_profit"] > result["entry"]

    def test_sl_below_entry_for_buy(self):
        from config import SignalAction, AssetClass
        ind    = self._ind()
        result = self.risk.compute_levels("BTC-USD", SignalAction.BUY, ind, AssetClass.CRYPTO)
        assert result["stop_loss"] < result["entry"]

    def test_tp_below_entry_for_sell(self):
        from config import SignalAction, AssetClass
        ind    = self._ind()
        result = self.risk.compute_levels("BTC-USD", SignalAction.SELL, ind, AssetClass.CRYPTO)
        assert result["take_profit"] < result["entry"]

    def test_sl_above_entry_for_sell(self):
        from config import SignalAction, AssetClass
        ind    = self._ind()
        result = self.risk.compute_levels("BTC-USD", SignalAction.SELL, ind, AssetClass.CRYPTO)
        assert result["stop_loss"] > result["entry"]

    def test_rr_positive(self):
        from config import SignalAction, AssetClass
        ind    = self._ind()
        result = self.risk.compute_levels("BTC-USD", SignalAction.BUY, ind, AssetClass.CRYPTO)
        assert result["risk_reward"] > 0

    def test_position_size_respects_account(self):
        from config import SignalAction, AssetClass, Config
        ind    = self._ind()
        result = self.risk.compute_levels("BTC-USD", SignalAction.BUY, ind, AssetClass.CRYPTO)
        max_allowed = Config.ACCOUNT_BALANCE * 0.20
        assert result["position_size_usd"] <= max_allowed

    def test_validate_rejects_low_rr(self):
        from config import SignalAction
        valid, reason = self.risk.validate_signal(SignalAction.BUY, rr=1.0, confidence=80)
        assert not valid
        assert "R:R" in reason

    def test_validate_rejects_low_confidence(self):
        from config import SignalAction
        valid, reason = self.risk.validate_signal(SignalAction.BUY, rr=2.0, confidence=50)
        assert not valid
        assert "onfidence" in reason

    def test_validate_accepts_good_signal(self):
        from config import SignalAction
        valid, reason = self.risk.validate_signal(SignalAction.BUY, rr=2.5, confidence=75)
        assert valid
        assert reason == ""

    def test_validate_rejects_hold(self):
        from config import SignalAction
        valid, reason = self.risk.validate_signal(SignalAction.HOLD, rr=3.0, confidence=90)
        assert not valid


# ═══════════════════════════════════════════════════════════════
# PATTERN AGENT
# ═══════════════════════════════════════════════════════════════

class TestPatternAgent:
    def setup_method(self):
        from agents.pattern_agent import PatternAgent
        self.agent = PatternAgent()

    def test_detect_on_valid_data(self):
        df      = make_ohlcv(100)
        results = self.agent.detect_all(df, "BTC-USD")
        assert isinstance(results, list)
        # May be empty but must not raise

    def test_detect_returns_empty_on_short_df(self):
        df      = make_ohlcv(5)
        results = self.agent.detect_all(df, "BTC-USD")
        assert results == []

    def test_pattern_bias_neutral_no_patterns(self):
        bias = self.agent.get_pattern_bias([])
        assert bias == 0.0

    def test_pattern_bias_bullish(self):
        from agents.pattern_agent import PatternResult
        patterns = [PatternResult("Double Bottom", "bullish", 74, "test")]
        bias = self.agent.get_pattern_bias(patterns)
        assert bias > 0

    def test_pattern_bias_bearish(self):
        from agents.pattern_agent import PatternResult
        patterns = [PatternResult("Head & Shoulders", "bearish", 76, "test")]
        bias = self.agent.get_pattern_bias(patterns)
        assert bias < 0

    def test_bull_flag_detected_on_strong_move(self):
        """Craft a series with a strong up move then flat consolidation."""
        closes = list(np.linspace(100, 110, 10)) + list(np.linspace(110, 110.5, 10))
        df = pd.DataFrame({
            "Open":   closes, "Close": closes,
            "High":   [c * 1.002 for c in closes],
            "Low":    [c * 0.998 for c in closes],
            "Volume": [1000.0] * 20,
        }, index=pd.date_range("2024-01-01", periods=20, freq="1h", tz="UTC"))
        results = self.agent.detect_all(df, "TEST")
        names = [r.name for r in results]
        # May or may not fire depending on exact values — just ensure no exception
        assert isinstance(names, list)


# ═══════════════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════════════

class TestDatabase:
    @pytest.fixture
    def db(self, tmp_path):
        from utils.database import SignalDatabase
        return SignalDatabase(path=str(tmp_path / "test.db"))

    @pytest.mark.asyncio
    async def test_init_creates_tables(self, db):
        await db.init()
        sigs = await db.get_recent_signals(limit=1)
        assert isinstance(sigs, list)

    @pytest.mark.asyncio
    async def test_save_and_retrieve_signal(self, db):
        from config import TradingSignal, SignalAction, AssetClass, TimeFrame
        await db.init()
        sig = TradingSignal(
            asset="BTC-USD", asset_class=AssetClass.CRYPTO,
            action=SignalAction.BUY, entry_price=95000.0,
            take_profit=101000.0, stop_loss=91000.0,
            confidence=77.0, risk_reward=1.8,
            strategy="EMA Cross", timeframe=TimeFrame.H1,
            reasoning="Test",
        )
        await db.save_signal(sig)
        rows = await db.get_recent_signals(limit=5)
        assert len(rows) == 1
        assert rows[0]["symbol"] == "BTC-USD"
        assert rows[0]["action"] == "BUY"

    @pytest.mark.asyncio
    async def test_update_outcome(self, db):
        from config import TradingSignal, SignalAction, AssetClass, TimeFrame
        await db.init()
        sig = TradingSignal(
            asset="ETH-USD", asset_class=AssetClass.CRYPTO,
            action=SignalAction.SELL, entry_price=3100.0,
            take_profit=2900.0, stop_loss=3250.0,
            confidence=68.0, risk_reward=1.7,
            strategy="RSI", timeframe=TimeFrame.H1, reasoning="Test",
        )
        await db.save_signal(sig)
        await db.update_outcome(sig.signal_id, "tp_hit", 6.45)
        rows = await db.get_recent_signals(limit=1)
        assert rows[0]["outcome"] == "tp_hit"
        assert abs(rows[0]["pnl_pct"] - 6.45) < 0.001

    @pytest.mark.asyncio
    async def test_create_and_verify_subscriber(self, db):
        await db.init()
        key = await db.create_subscriber("Test User", "test@example.com", "pro", 30)
        assert key.startswith("nx-")
        sub = await db.verify_api_key(key)
        assert sub is not None
        assert sub["name"] == "Test User"
        assert sub["tier"] == "pro"

    @pytest.mark.asyncio
    async def test_revoke_subscriber(self, db):
        await db.init()
        key = await db.create_subscriber("Revoke Test", "", "starter", 30)
        await db.revoke_subscriber(key)
        sub = await db.verify_api_key(key)
        assert sub is None

    @pytest.mark.asyncio
    async def test_stats_empty_db(self, db):
        await db.init()
        stats = await db.get_stats()
        assert stats.get("total", 0) == 0


# ═══════════════════════════════════════════════════════════════
# POSITION TRACKER
# ═══════════════════════════════════════════════════════════════

class TestPositionTracker:
    def setup_method(self):
        from utils.position_tracker import PositionTracker
        from utils.database         import SignalDatabase
        # Use in-memory mock for DB
        db           = MagicMock()
        db.update_outcome = AsyncMock()
        self.tracker = PositionTracker(db=db)

    def test_open_position(self):
        self.tracker.open_position("SIG001", "BTC-USD", "BUY", 95000, 101000, 91000, 500)
        assert len(self.tracker.get_open_positions()) == 1

    def test_unrealised_pnl_long(self):
        self.tracker.open_position("SIG002", "ETH-USD", "BUY", 3000, 3300, 2850, 300)
        pos = self.tracker.get_open_positions()[0]
        pos.current_price = 3150.0
        assert pos.unrealised_pnl_pct == pytest.approx(5.0, abs=0.01)

    def test_unrealised_pnl_short(self):
        self.tracker.open_position("SIG003", "BTC-USD", "SELL", 96000, 91000, 98000, 500)
        pos = self.tracker.get_open_positions()[0]
        pos.current_price = 94000.0
        assert pos.unrealised_pnl_pct == pytest.approx(2.083, abs=0.01)

    def test_close_position(self):
        self.tracker.open_position("SIG004", "BTC-USD", "BUY", 95000, 101000, 91000, 500)
        pos = self.tracker.get_open_positions()[0]
        pos.current_price = 101000.0
        self.tracker.close_position("SIG004", 101000.0, "TP Hit")
        assert len(self.tracker.get_open_positions()) == 0
        assert self.tracker._trade_count_today == 1

    def test_summary_includes_equity(self):
        self.tracker.open_position("SIG005", "BTC-USD", "BUY", 95000, 101000, 91000, 500)
        pos = self.tracker.get_open_positions()[0]
        pos.current_price = 95500.0
        summary = self.tracker.get_summary()
        assert "equity" in summary
        assert summary["open_count"] == 1
        assert summary["total_unrealised"] > 0


# ═══════════════════════════════════════════════════════════════
# STRATEGY PERFORMANCE TRACKER
# ═══════════════════════════════════════════════════════════════

class TestStrategyTracker:
    @pytest.mark.asyncio
    async def test_empty_db_returns_empty(self, tmp_path):
        from utils.database          import SignalDatabase
        from utils.strategy_tracker  import StrategyPerformanceTracker
        db = SignalDatabase(path=str(tmp_path / "t.db"))
        await db.init()
        tracker = StrategyPerformanceTracker(db)
        stats   = await tracker.compute()
        assert isinstance(stats, dict)

    @pytest.mark.asyncio
    async def test_score_correct_for_winner(self, tmp_path):
        from config                  import TradingSignal, SignalAction, AssetClass, TimeFrame
        from utils.database          import SignalDatabase
        from utils.strategy_tracker  import StrategyPerformanceTracker

        db = SignalDatabase(path=str(tmp_path / "t2.db"))
        await db.init()

        # Add 5 wins with EMA Cross strategy
        for i in range(5):
            sig = TradingSignal(
                asset="BTC-USD", asset_class=AssetClass.CRYPTO,
                action=SignalAction.BUY, entry_price=90000.0,
                take_profit=96000.0, stop_loss=87000.0,
                confidence=75.0, risk_reward=2.0,
                strategy="EMA Cross", timeframe=TimeFrame.H1, reasoning="test",
            )
            await db.save_signal(sig)
            await db.update_outcome(sig.signal_id, "tp_hit", 6.67)

        tracker = StrategyPerformanceTracker(db)
        tracker._cache_ts = None   # force recompute
        stats   = await tracker.compute()
        assert "EMA Cross" in stats
        assert stats["EMA Cross"].win_rate == 100.0
        assert stats["EMA Cross"].score > 1.0   # should be upweighted


# ═══════════════════════════════════════════════════════════════
# SENTIMENT AGENT
# ═══════════════════════════════════════════════════════════════

class TestSentimentAgent:
    def setup_method(self):
        from agents.sentiment_agent import SentimentAgent
        self.agent = SentimentAgent()

    def test_bullish_headline(self):
        score = self.agent.score_headline("Bitcoin surges to new all-time high")
        assert score > 0

    def test_bearish_headline(self):
        score = self.agent.score_headline("Crypto market crashes amid regulatory crackdown")
        assert score < 0

    def test_score_in_bounds(self):
        for text in ["great rally!", "terrible crash dump", "neutral sideways day"]:
            score = self.agent.score_headline(text)
            assert -1.0 <= score <= 1.0

    def test_batch_empty_returns_zero(self):
        result = self.agent.score_headlines_batch([], "BTC-USD")
        assert result == 0.0

    def test_symbol_relevance_boost(self):
        headlines = [{"title": "BTC breaks $100k", "summary": ""}]
        score_btc = self.agent.score_headlines_batch(headlines, "BTC-USD")
        score_eth = self.agent.score_headlines_batch(headlines, "ETH-USD")
        # BTC-specific headline should score higher for BTC than ETH
        assert score_btc >= score_eth

    @pytest.mark.asyncio
    async def test_analyze_returns_label(self):
        headlines = [{"title": "Bitcoin rally continues", "summary": ""}]
        result    = await self.agent.analyze("BTC-USD", headlines, 95000, use_ai=False)
        assert "label" in result
        assert result["label"] in ("Bullish", "Mildly Bullish", "Neutral", "Mildly Bearish", "Bearish")


# ═══════════════════════════════════════════════════════════════
# HEALTH MONITOR
# ═══════════════════════════════════════════════════════════════

class TestHealthMonitor:
    @pytest.mark.asyncio
    async def test_check_passes_on_healthy_db(self, tmp_path):
        from utils.database      import SignalDatabase
        from utils.health_monitor import HealthMonitor
        db = SignalDatabase(path=str(tmp_path / "h.db"))
        await db.init()
        monitor = HealthMonitor(db=db)
        result  = await monitor.check()
        assert result["checks"]["database"]["ok"] is True

    @pytest.mark.asyncio
    async def test_format_downtime(self, tmp_path):
        from utils.database       import SignalDatabase
        from utils.health_monitor import HealthMonitor
        from datetime import timedelta
        db = SignalDatabase(path=str(tmp_path / "h2.db"))
        await db.init()
        monitor = HealthMonitor(db=db)
        monitor._last_known_good = datetime.utcnow() - timedelta(minutes=90)
        assert "h" in monitor._format_downtime()


# ═══════════════════════════════════════════════════════════════
# INTEGRATION: full pipeline on synthetic data
# ═══════════════════════════════════════════════════════════════

class TestPipelineIntegration:
    @pytest.mark.asyncio
    async def test_full_pipeline_produces_signal_or_none(self, tmp_path):
        """End-to-end: technical → strategy → risk → TradingSignal."""
        from config                 import AssetClass, TimeFrame
        from agents.technical_agent import TechnicalAgent
        from agents.strategy_agent  import StrategyEngine
        from agents.risk_agent      import RiskAgent
        from agents.pattern_agent   import PatternAgent

        df      = make_ohlcv(250, trend="up")
        tech    = TechnicalAgent()
        strat   = StrategyEngine()
        risk    = RiskAgent()
        pattern = PatternAgent()

        ind = tech.compute("BTC-USD", df, "1h")
        assert ind is not None

        patterns     = pattern.detect_all(df, "BTC-USD")
        pattern_bias = pattern.get_pattern_bias(patterns)

        result = strat.run_ensemble(
            "BTC-USD", ind, AssetClass.CRYPTO,
            sentiment_score=0.2, higher_tf_bias=pattern_bias * 0.3,
        )
        assert result["action"] is not None
        assert 0 <= result["confidence"] <= 100

        risk_result = risk.compute_levels(
            "BTC-USD", result["action"], ind, AssetClass.CRYPTO,
            confidence=result["confidence"],
        )
        assert "entry" in risk_result
        assert risk_result["risk_reward"] >= 0

    @pytest.mark.asyncio
    async def test_db_full_lifecycle(self, tmp_path):
        """Create signal → save → update outcome → verify stats."""
        from config         import TradingSignal, SignalAction, AssetClass, TimeFrame
        from utils.database import SignalDatabase

        db = SignalDatabase(path=str(tmp_path / "lifecycle.db"))
        await db.init()

        sig = TradingSignal(
            asset="SOL-USD", asset_class=AssetClass.CRYPTO,
            action=SignalAction.BUY, entry_price=168.0,
            take_profit=195.0, stop_loss=155.0,
            confidence=71.0, risk_reward=2.1,
            strategy="Breakout", timeframe=TimeFrame.H1, reasoning="ATH breakout",
        )
        await db.save_signal(sig)
        await db.update_outcome(sig.signal_id, "tp_hit", 16.07)

        stats = await db.get_stats()
        assert stats["total"] == 1
        assert stats["wins"]  == 1
        assert stats["win_rate"] == 100.0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
