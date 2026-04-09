"""
NEXUS AI - Telegram Bot
Publishes signals to channel + handles subscriber commands.
Commands:
  /start    — welcome + subscribe
  /signals  — last 5 signals
  /stats    — win rate + performance
  /status   — system health
  /help     — command list
"""

import asyncio
from datetime import datetime
from loguru import logger
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes, CallbackQueryHandler
)
from telegram.constants import ParseMode
from config import Config, TradingSignal
from utils.database import SignalDatabase


class TelegramPublisher:
    """Publishes TradingSignal objects and text messages to a Telegram channel."""

    def __init__(self):
        self.bot = Bot(token=Config.TELEGRAM_BOT_TOKEN)

    async def publish(self, signal: TradingSignal):
        """Send a signal message to the channel."""
        if not Config.TELEGRAM_CHANNEL_ID:
            logger.warning("[Telegram] TELEGRAM_CHANNEL_ID not set")
            return
        try:
            msg = signal.to_telegram_message()
            await self.bot.send_message(
                chat_id=Config.TELEGRAM_CHANNEL_ID,
                text=msg,
                parse_mode=ParseMode.MARKDOWN,
            )
            logger.success(f"[Telegram] Published {signal.signal_id} to channel")
        except Exception as e:
            logger.error(f"[Telegram] publish failed: {e}")

    async def publish_text(self, text: str):
        """Send a plain text/markdown message to the channel (for outcome notifications)."""
        if not Config.TELEGRAM_CHANNEL_ID:
            return
        try:
            await self.bot.send_message(
                chat_id=Config.TELEGRAM_CHANNEL_ID,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            logger.error(f"[Telegram] publish_text failed: {e}")

    async def send_admin(self, text: str):
        """Send a message to the admin."""
        if not Config.TELEGRAM_ADMIN_ID:
            return
        try:
            await self.bot.send_message(
                chat_id=Config.TELEGRAM_ADMIN_ID,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            logger.error(f"[Telegram] send_admin failed: {e}")


class NexusBot:
    """
    Full Telegram bot with command handlers for subscribers.
    Runs as a parallel async task alongside the signal engine.
    """

    def __init__(self, db: SignalDatabase, orchestrator=None):
        self.db             = db
        self.orchestrator   = orchestrator
        self.publisher      = TelegramPublisher()
        self.position_tracker = None   # injected by main.py
        self.app            = Application.builder().token(Config.TELEGRAM_BOT_TOKEN).build()
        self._register_handlers()

    def _register_handlers(self):
        self.app.add_handler(CommandHandler("start",       self.cmd_start))
        self.app.add_handler(CommandHandler("signals",     self.cmd_signals))
        self.app.add_handler(CommandHandler("stats",       self.cmd_stats))
        self.app.add_handler(CommandHandler("status",      self.cmd_status))
        self.app.add_handler(CommandHandler("subscribe",   self.cmd_subscribe))
        self.app.add_handler(CommandHandler("performance", self.cmd_performance))
        self.app.add_handler(CommandHandler("positions",   self.cmd_positions))
        self.app.add_handler(CommandHandler("alert",       self.cmd_alert))
        self.app.add_handler(CommandHandler("help",        self.cmd_help))
        self.app.add_handler(CommandHandler("run",         self.cmd_run))
        self.app.add_handler(CallbackQueryHandler(self.handle_callback))

    # ── Command Handlers ──────────────────────────────────────

    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        keyboard = [
            [InlineKeyboardButton("📊 Latest Signals", callback_data="signals"),
             InlineKeyboardButton("📈 Stats",           callback_data="stats")],
            [InlineKeyboardButton("⚙️ System Status",  callback_data="status")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "👋 Welcome to *NEXUS AI Trading Signals*\n\n"
            "🤖 I'm a multi-agent AI system that analyzes crypto, stocks, and forex "
            "to generate high-confidence trading signals with dynamic TP & SL.\n\n"
            "📡 *How it works:*\n"
            "• 5 specialized agents crawl and analyze markets 24/7\n"
            "• Signals only fire when confidence ≥ 65%\n"
            "• Every signal includes entry, TP, SL, and R:R ratio\n\n"
            "⚠️ _Always do your own research. Never risk more than 1-2% per trade._",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup,
        )

    async def cmd_signals(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        signals = await self.db.get_recent_signals(limit=5)
        if not signals:
            await update.message.reply_text("No signals yet. Run `/run` to generate.")
            return

        msg = "📊 *Last 5 Signals*\n━━━━━━━━━━━━━━━━━━━━\n"
        for s in signals:
            emoji  = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}.get(s["action"], "⚪")
            outcome_emoji = {
                "open": "⏳", "tp_hit": "✅", "sl_hit": "❌", "expired": "⏰"
            }.get(s.get("outcome", "open"), "⏳")
            msg += (
                f"{emoji} *{s['symbol']}* — {s['action']} {outcome_emoji}\n"
                f"  Entry: `${s['entry_price']:,.4f}` "
                f"TP: `${s['take_profit']:,.4f}` "
                f"SL: `${s['stop_loss']:,.4f}`\n"
                f"  Conf: `{s['confidence']:.0f}%` | R:R `{s['risk_reward']:.1f}:1`\n"
                f"  _{s['strategy']}_\n\n"
            )
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    async def cmd_stats(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        stats = await self.db.get_stats()
        if not stats or not stats.get("total"):
            await update.message.reply_text("No closed signals yet to compute stats.")
            return

        await update.message.reply_text(
            f"📈 *Performance Stats*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Total Signals: `{stats['total']}`\n"
            f"Wins (TP hit): `{stats['wins']}`\n"
            f"Losses (SL hit): `{stats['losses']}`\n"
            f"🎯 Win Rate: `{stats['win_rate']:.1f}%`\n"
            f"📊 Avg R:R: `{stats['avg_rr']:.2f}:1`\n"
            f"🧠 Avg Confidence: `{stats['avg_conf']:.0f}%`",
            parse_mode=ParseMode.MARKDOWN,
        )

    async def cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        mode = "📄 Paper Trading" if Config.PAPER_TRADING else "🔴 LIVE Trading"
        await update.message.reply_text(
            f"⚙️ *System Status*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🕐 Time: `{now}`\n"
            f"🔄 Interval: `{Config.SIGNAL_INTERVAL_MINS} min`\n"
            f"💰 Account: `${Config.ACCOUNT_BALANCE:,.0f}`\n"
            f"⚠️ Risk/Trade: `{Config.RISK_PER_TRADE*100:.1f}%`\n"
            f"🎯 Min Confidence: `{Config.MIN_CONFIDENCE:.0f}%`\n"
            f"📊 Watchlist: `{len(Config.all_symbols())} symbols`\n"
            f"🤖 Mode: {mode}\n"
            f"✅ All agents operational",
            parse_mode=ParseMode.MARKDOWN,
        )

    async def cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🤖 *NEXUS AI Commands*\n\n"
            "/start — Welcome + quick actions\n"
            "/signals — Last 5 signals\n"
            "/stats — Win rate & performance\n"
            "/status — System health\n"
            "/subscribe — Get premium access\n"
            "/help — This message\n\n"
            "📡 Signals are auto-published every "
            f"{Config.SIGNAL_INTERVAL_MINS} minutes.",
            parse_mode=ParseMode.MARKDOWN,
        )

    async def cmd_positions(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """Show all open paper positions with live P&L."""
        if self.position_tracker:
            msg = self.position_tracker.format_positions_message()
        else:
            msg = "📋 Position tracker not connected."
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    async def cmd_alert(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """
        Set a price alert. Usage: /alert BTC-USD 100000
        Fires once when price crosses the target.
        """
        args = ctx.args
        if not args or len(args) < 2:
            await update.message.reply_text(
                "Usage: `/alert <symbol> <target_price>`\n"
                "Example: `/alert BTC-USD 100000`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        symbol = args[0].upper()
        try:
            target = float(args[1].replace(",", ""))
        except ValueError:
            await update.message.reply_text("Invalid price. Example: `/alert BTC-USD 100000`",
                                            parse_mode=ParseMode.MARKDOWN)
            return

        # Store alert in context for the polling task
        if not hasattr(self, "_price_alerts"):
            self._price_alerts = []
            asyncio.create_task(self._price_alert_loop())
        self._price_alerts.append({
            "symbol": symbol, "target": target,
            "chat_id": update.effective_chat.id,
            "triggered": False,
        })
        await update.message.reply_text(
            f"🔔 Alert set: *{symbol}* → `${target:,.2f}`\n"
            f"_You'll be notified when price crosses this level._",
            parse_mode=ParseMode.MARKDOWN,
        )

    async def _price_alert_loop(self):
        """Background loop checking price alerts every 60s."""
        import yfinance as yf
        while True:
            try:
                if not hasattr(self, "_price_alerts"):
                    break
                active = [a for a in self._price_alerts if not a["triggered"]]
                if not active:
                    await asyncio.sleep(60)
                    continue
                # Batch fetch unique symbols
                symbols = list(set(a["symbol"] for a in active))
                prices  = {}
                for sym in symbols:
                    try:
                        prices[sym] = float(yf.Ticker(sym).fast_info.last_price)
                    except Exception:
                        pass
                for alert in active:
                    price = prices.get(alert["symbol"])
                    if not price:
                        continue
                    # Fire if within 0.5% of target
                    if abs(price - alert["target"]) / alert["target"] < 0.005:
                        try:
                            await self.app.bot.send_message(
                                chat_id=alert["chat_id"],
                                text=(
                                    f"🔔 *Price Alert Triggered!*\n"
                                    f"*{alert['symbol']}* is at `${price:,.4f}`\n"
                                    f"Target was `${alert['target']:,.2f}`"
                                ),
                                parse_mode=ParseMode.MARKDOWN,
                            )
                            alert["triggered"] = True
                        except Exception:
                            pass
            except Exception as e:
                logger.error(f"[AlertLoop] {e}")
            await asyncio.sleep(60)

    async def cmd_subscribe(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """Show subscription options with pricing."""
        keyboard = [
            [InlineKeyboardButton("🪙 Starter — $29/mo", callback_data="sub_starter"),
             InlineKeyboardButton("🚀 Pro — $79/mo",     callback_data="sub_pro")],
            [InlineKeyboardButton("🏢 Enterprise — $299/mo", callback_data="sub_enterprise")],
        ]
        await update.message.reply_text(
            "💳 *NEXUS AI — Premium Plans*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "🪙 *Starter — $29/mo*\n"
            "• Crypto signals only (BTC, ETH, SOL, BNB)\n"
            "• Entry + TP + SL on every signal\n"
            "• Up to 15 signals/week\n\n"
            "🚀 *Pro — $79/mo* ⭐ Most Popular\n"
            "• Crypto + Stocks + Forex signals\n"
            "• AI sentiment analysis included\n"
            "• Multi-timeframe confirmation\n"
            "• Priority group access\n"
            "• Up to 40 signals/week\n\n"
            "🏢 *Enterprise — $299/mo*\n"
            "• Everything in Pro\n"
            "• Webhook/API delivery\n"
            "• Custom watchlist (30 symbols)\n"
            "• Backtest reports on request\n\n"
            "_To subscribe, contact admin or visit the website._",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    async def cmd_performance(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """Show last 10 resolved signals with outcomes."""
        signals = await self.db.get_recent_signals(limit=30)
        closed  = [s for s in signals if s.get("outcome") not in ("open", None)][:10]
        if not closed:
            await update.message.reply_text("No resolved signals yet — signals close when TP or SL is hit.")
            return
        wins   = sum(1 for s in closed if s["outcome"] == "tp_hit")
        losses = sum(1 for s in closed if s["outcome"] == "sl_hit")
        msg    = f"📊 *Last {len(closed)} Resolved Signals*\n━━━━━━━━━━━━━━━━━━━━\n"
        for s in closed:
            e  = "✅" if s["outcome"] == "tp_hit" else "❌" if s["outcome"] == "sl_hit" else "⏰"
            pnl = s.get("pnl_pct")
            pnl_str = f"`{pnl:+.2f}%`" if pnl is not None else "`—`"
            msg += f"{e} *{s['symbol']}* {s['action']} → {pnl_str}\n"
        msg += f"━━━━━━━━━━━━━━━━━━━━\n✅ {wins} wins  ❌ {losses} losses  🎯 {wins/(wins+losses)*100:.0f}% win rate"
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    async def cmd_run(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """Admin-only: trigger a manual signal cycle."""
        if update.effective_user.id != Config.TELEGRAM_ADMIN_ID:
            await update.message.reply_text("⛔ Admin only.")
            return
        if not self.orchestrator:
            await update.message.reply_text("Orchestrator not connected.")
            return
        await update.message.reply_text("🔄 Running signal cycle…")
        signals = await self.orchestrator.run_cycle()
        await update.message.reply_text(
            f"✅ Cycle complete. Generated *{len(signals)}* signal(s).",
            parse_mode=ParseMode.MARKDOWN,
        )

    async def handle_callback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        if q.data == "signals":
            await self.cmd_signals(q, ctx)
        elif q.data == "stats":
            await self.cmd_stats(q, ctx)
        elif q.data == "status":
            await self.cmd_status(q, ctx)
        elif q.data in ("sub_starter", "sub_pro", "sub_enterprise"):
            tier = q.data.replace("sub_", "")
            prices = {"starter": "$29/mo", "pro": "$79/mo", "enterprise": "$299/mo"}
            await q.message.reply_text(
                f"💳 *{tier.title()} Plan — {prices[tier]}*\n\n"
                f"To subscribe, contact the admin:\n"
                f"_Send a message to the bot admin with your preferred plan "
                f"and payment will be arranged. You'll receive an API key "
                f"and channel invite link within 24 hours._\n\n"
                f"Or visit the website for instant checkout.",
                parse_mode=ParseMode.MARKDOWN,
            )

    # ── Lifecycle ─────────────────────────────────────────────

    async def start(self):
        """Initialize and start polling."""
        await self.db.init()
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(drop_pending_updates=True)
        logger.success("[Telegram Bot] Started and polling")

    async def stop(self):
        await self.app.updater.stop()
        await self.app.stop()
        await self.app.shutdown()
        logger.info("[Telegram Bot] Stopped")
