"""
NEXUS AI - Signal Orchestrator
The brain: coordinates all 6 agents and produces final TradingSignal objects.
This is the main loop that runs on schedule.

Pipeline per symbol:
  Crawler → Technical → Sentiment → PatternAgent → Strategy → Risk → Signal → DB → Publish
"""

import asyncio
from datetime import datetime, timedelta
from loguru import logger
from config import Config, TradingSignal, SignalAction, TimeFrame
from agents.crawler_agent    import DataCrawlerAgent
from agents.technical_agent  import TechnicalAgent
from agents.sentiment_agent  import SentimentAgent
from agents.pattern_agent    import PatternAgent
from agents.strategy_agent   import StrategyEngine
from agents.risk_agent       import RiskAgent
from utils.database          import SignalDatabase
from utils.logger_setup      import setup_logger
from utils.strategy_tracker  import StrategyPerformanceTracker


class SignalOrchestrator:
    """
    Wires together all 6 agents into a complete signal pipeline.

    Flow per symbol:
      Crawler → Technical → Sentiment → Pattern → Strategy → Risk → Signal → DB → Publish
    """

    def __init__(self):
        setup_logger()
        self.crawler   = DataCrawlerAgent()
        self.technical = TechnicalAgent()
        self.sentiment = SentimentAgent()
        self.pattern   = PatternAgent()
        self.strategy  = StrategyEngine()
        self.risk      = RiskAgent()
        self.db        = SignalDatabase()
        self.strat_tracker = StrategyPerformanceTracker(self.db)
        self._publisher        = None
        self._webhook_dispatch = None
        self._executor         = None
        self._last_signal: dict[str, tuple[str, datetime]] = {}
        self._cycle_count = 0
        logger.info("SignalOrchestrator initialized (6 agents)")

    def set_publisher(self, publisher):
        """Inject a Telegram publisher after construction."""
        self._publisher = publisher

    def set_webhook_dispatcher(self, fn):
        """Inject the webhook dispatch coroutine from api/routes.py."""
        self._webhook_dispatch = fn

    def set_executor(self, executor):
        """Inject a BrokerExecutor for auto-executing signals."""
        self._executor = executor

    # ──────────────────────────────────────────────────────────
    # Per-Symbol Pipeline
    # ──────────────────────────────────────────────────────────

    async def process_symbol(self, symbol: str, crawled: dict) -> TradingSignal | None:
        """Full pipeline for one symbol. Returns TradingSignal or None."""

        data = crawled.get(symbol)
        if not data:
            return None

        asset_class   = data["asset_class"]
        current_price = data["current_price"]
        ohlcv_frames  = data["ohlcv"]
        headlines     = data.get("headlines", [])

        if not current_price:
            logger.warning(f"No price for {symbol}, skipping")
            return None

        # 1. Technical indicators (primary timeframe: 1h; higher TF: 4h)
        inds_by_tf  = self.technical.compute_all_timeframes(symbol, ohlcv_frames)
        ind_primary = inds_by_tf.get("1h") or inds_by_tf.get("15m")
        ind_higher  = inds_by_tf.get("4h") or inds_by_tf.get("1d")

        if ind_primary is None:
            logger.warning(f"No indicators for {symbol}, skipping")
            return None

        higher_tf_bias = ind_higher.trend_bias if ind_higher else 0.0

        # 2. Sentiment
        sentiment_result = await self.sentiment.analyze(
            symbol, headlines, current_price, use_ai=True
        )
        sentiment_score = sentiment_result["score"]

        # 3. Pattern detection — adds bias modifier to strategy ensemble
        df_primary   = ohlcv_frames.get("1h") or ohlcv_frames.get("15m")
        patterns     = self.pattern.detect_all(df_primary, symbol) if df_primary is not None else []
        pattern_bias = self.pattern.get_pattern_bias(patterns)   # -100 to +100

        # 4. Strategy ensemble (now includes pattern bias)
        strategy_result = self.strategy.run_ensemble(
            symbol=symbol,
            ind=ind_primary,
            asset_class=asset_class,
            sentiment_score=sentiment_score,
            higher_tf_bias=higher_tf_bias + pattern_bias * 0.3,  # blend pattern bias into HTF
        )

        action     = strategy_result["action"]
        confidence = strategy_result["confidence"]

        # Append detected pattern names to reasoning
        if patterns:
            pattern_names = ", ".join(p.name for p in patterns)
            strategy_result["reasoning"] += f" | Patterns: {pattern_names}"

        # Duplicate-signal guard: suppress same direction within 4 hours
        last = self._last_signal.get(symbol)
        if last:
            last_action, last_time = last
            age_h = (datetime.utcnow() - last_time).total_seconds() / 3600
            if last_action == action.value and age_h < 4:
                logger.info(f"[Orchestrator] {symbol}: duplicate {action.value} suppressed ({age_h:.1f}h ago)")
                return None

        # 5. Risk levels
        risk_result = self.risk.compute_levels(
            symbol=symbol,
            action=action,
            ind=ind_primary,
            asset_class=asset_class,
            confidence=confidence,
        )

        if not risk_result:
            return None

        # 6. Validate
        is_valid, rejection = self.risk.validate_signal(
            action, risk_result["risk_reward"], confidence
        )
        if not is_valid:
            logger.info(f"[Orchestrator] {symbol}: signal rejected — {rejection}")
            return None

        # 7. Build TradingSignal
        signal = TradingSignal(
            asset=symbol,
            asset_class=asset_class,
            action=action,
            entry_price=risk_result["entry"],
            take_profit=risk_result["take_profit"],
            stop_loss=risk_result["stop_loss"],
            confidence=confidence,
            risk_reward=risk_result["risk_reward"],
            strategy=strategy_result["strategy_name"],
            timeframe=TimeFrame.H1,
            reasoning=strategy_result["reasoning"],
            sentiment_score=sentiment_score,
        )

        # Record for duplicate guard
        self._last_signal[symbol] = (action.value, datetime.utcnow())

        # Auto-execute via broker (paper or live)
        if self._executor:
            try:
                await self._executor.execute(signal)
            except Exception as e:
                logger.warning(f"[Orchestrator] executor error for {symbol}: {e}")

        logger.success(
            f"[Orchestrator] ✅ SIGNAL: {symbol} {action.value} "
            f"entry={signal.entry_price} TP={signal.take_profit} "
            f"SL={signal.stop_loss} conf={confidence:.0f}% "
            f"patterns={len(patterns)}"
        )
        return signal

    # ──────────────────────────────────────────────────────────
    # Full Cycle
    # ──────────────────────────────────────────────────────────

    async def run_cycle(self) -> list[TradingSignal]:
        """
        One full signal cycle: crawl → analyze → publish.
        Called by the scheduler every SIGNAL_INTERVAL_MINS minutes.
        """
        logger.info("═══════════════ SIGNAL CYCLE START ═══════════════")
        start = datetime.utcnow()
        self._cycle_count += 1

        # Refresh dynamic strategy weights every 10 cycles (~2.5h at 15m interval)
        if self._cycle_count % 10 == 1:
            try:
                weights = await self.strat_tracker.get_weight_map()
                self.strategy.update_weights(weights)
            except Exception as e:
                logger.warning(f"[Orchestrator] strategy weight refresh failed: {e}")

        # 1. Crawl all data
        crawled = await self.crawler.crawl_all()

        # 2. Process symbols concurrently
        tasks = [
            self.process_symbol(sym, crawled)
            for sym in Config.all_symbols()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        signals = []
        for r in results:
            if isinstance(r, TradingSignal):
                signals.append(r)
            elif isinstance(r, Exception):
                logger.error(f"Symbol processing error: {r}")

        # 3. Persist to DB
        for sig in signals:
            await self.db.save_signal(sig)

        # 4. Publish — Telegram + webhooks in parallel
        publish_tasks = []
        for sig in signals:
            if self._publisher:
                publish_tasks.append(self._publisher.publish(sig))
            if self._webhook_dispatch:
                publish_tasks.append(self._webhook_dispatch(sig))
        if publish_tasks:
            await asyncio.gather(*publish_tasks, return_exceptions=True)

        elapsed = (datetime.utcnow() - start).total_seconds()
        logger.info(
            f"═══════════════ CYCLE COMPLETE: {len(signals)} signals "
            f"in {elapsed:.1f}s ═══════════════"
        )
        return signals
