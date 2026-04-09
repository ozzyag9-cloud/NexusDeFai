"""
NEXUS AI - Main Entry Point
Full system: signal scheduler + Telegram bot + outcome tracker +
             position tracker + live price feed + health monitor + API server.

Usage:
  python main.py             # full live system
  python main.py --backtest  # backtest all watchlist symbols → HTML report
  python main.py --once      # one signal cycle then exit
"""

import asyncio
import argparse
import uvicorn
from loguru import logger
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval  import IntervalTrigger

from config                    import Config
from orchestrator               import SignalOrchestrator
from telegram_bot.bot           import NexusBot, TelegramPublisher
from utils.database             import SignalDatabase
from utils.outcome_tracker      import OutcomeTracker
from utils.health_monitor       import HealthMonitor
from utils.position_tracker     import PositionTracker
from utils.price_feed           import price_feed
from utils.broker_executor      import BrokerExecutor
from utils.logger_setup         import setup_logger


async def run_live():
    setup_logger()
    logger.info("╔══════════════════════════════════════╗")
    logger.info("║       NEXUS AI  —  Starting Up       ║")
    logger.info("╚══════════════════════════════════════╝")
    logger.info(f"  Paper trading  : {Config.PAPER_TRADING}")
    logger.info(f"  Symbols        : {len(Config.all_symbols())}")
    logger.info(f"  Interval       : {Config.SIGNAL_INTERVAL_MINS} min")
    logger.info(f"  Risk per trade : {Config.RISK_PER_TRADE*100:.1f}%")
    logger.info(f"  Account balance: ${Config.ACCOUNT_BALANCE:,.0f}")

    # ── Core services ──────────────────────────────────────────
    db        = SignalDatabase()
    await db.init()

    publisher = TelegramPublisher()

    # ── Position tracker + broker executor ────────────────────
    pos_tracker = PositionTracker(db=db, publisher=publisher)
    executor    = BrokerExecutor(position_tracker=pos_tracker)

    # ── Orchestrator (6 agents) ────────────────────────────────
    orchestrator = SignalOrchestrator()
    orchestrator.set_publisher(publisher)
    orchestrator.set_executor(executor)        # new: auto-execute signals

    try:
        from api.routes import dispatch_webhooks
        orchestrator.set_webhook_dispatcher(dispatch_webhooks)
        logger.info("  Webhooks       : enabled")
    except Exception:
        logger.warning("  Webhooks       : api/routes not loaded")

    # ── Supporting services ────────────────────────────────────
    tracker = OutcomeTracker(db=db, publisher=publisher)
    monitor = HealthMonitor(db=db, publisher=publisher)
    bot     = NexusBot(db=db, orchestrator=orchestrator)
    bot.position_tracker = pos_tracker

    # ── Scheduler ──────────────────────────────────────────────
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        orchestrator.run_cycle,
        IntervalTrigger(minutes=Config.SIGNAL_INTERVAL_MINS),
        id="signal_cycle", max_instances=1, misfire_grace_time=60,
    )
    scheduler.add_job(
        tracker.check_all_open,
        IntervalTrigger(minutes=15),
        id="outcome_tracker", max_instances=1, misfire_grace_time=60,
    )
    scheduler.start()
    monitor.scheduler = scheduler
    logger.success(f"Scheduler running — signals every {Config.SIGNAL_INTERVAL_MINS}m")

    # ── Start background tasks ─────────────────────────────────
    await price_feed.start()
    logger.success("Live price feed started")

    await orchestrator.run_cycle()      # immediate first cycle
    await bot.start()
    logger.success("Telegram bot polling")

    api_cfg  = uvicorn.Config(
        "api.routes:app", host="0.0.0.0", port=8000,
        log_level="warning", loop="none",
    )
    server       = uvicorn.Server(api_cfg)
    api_task     = asyncio.create_task(server.serve())
    monitor_task = asyncio.create_task(monitor.run_loop())
    pos_task     = asyncio.create_task(pos_tracker.run_loop())

    logger.success(
        "All systems go 🚀\n"
        "  API      → http://0.0.0.0:8000/docs\n"
        "  Dashboard→ http://0.0.0.0:8000/dashboard"
    )

    try:
        await publisher.send_admin(
            f"🚀 *NEXUS AI started*\n"
            f"Paper: `{Config.PAPER_TRADING}` | "
            f"Symbols: `{len(Config.all_symbols())}` | "
            f"Interval: `{Config.SIGNAL_INTERVAL_MINS}m`\n"
            f"Dashboard: `http://YOUR_SERVER:8000/dashboard`"
        )
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down…")
    finally:
        scheduler.shutdown(wait=False)
        await bot.stop()
        await price_feed.stop()
        server.should_exit = True
        for t in (monitor_task, pos_task):
            t.cancel()
        await api_task
        logger.info("NEXUS AI stopped cleanly.")


async def run_backtest():
    from backtester.report_generator import run as report_run
    setup_logger()
    report_run()


async def run_once():
    setup_logger()
    db = SignalDatabase()
    await db.init()
    orchestrator = SignalOrchestrator()
    signals = await orchestrator.run_cycle()
    print(f"\n{'═'*56}\n  ✅  {len(signals)} signal(s) generated\n{'═'*56}\n")
    for s in signals:
        print(s.to_telegram_message())
        print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NEXUS AI Trading System")
    parser.add_argument("--backtest", action="store_true", help="Run backtest suite")
    parser.add_argument("--once",     action="store_true", help="One cycle then exit")
    args = parser.parse_args()

    if args.backtest:
        asyncio.run(run_backtest())
    elif args.once:
        asyncio.run(run_once())
    else:
        asyncio.run(run_live())
