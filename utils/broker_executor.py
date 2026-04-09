"""
NEXUS AI - Broker Executor
Paper trade executor for Binance (testnet) and Alpaca (paper).
Live trading is disabled until PAPER_TRADING=false in .env AND
the user has verified performance over 90+ days.

Modes:
  PAPER_TRADING=true  → simulate fills, log to DB, update PositionTracker
  PAPER_TRADING=false → send real orders (Binance/Alpaca)
"""

import asyncio
import hashlib
import hmac
import time
import aiohttp
from datetime import datetime
from loguru import logger
from config import Config, TradingSignal, AssetClass, SignalAction


class BrokerExecutor:
    """
    Handles trade execution for paper and live modes.
    Start with PAPER_TRADING=true — always.
    """

    BINANCE_TESTNET = "https://testnet.binance.vision/api"
    BINANCE_LIVE    = "https://api.binance.com/api"
    ALPACA_PAPER    = "https://paper-api.alpaca.markets/v2"
    ALPACA_LIVE     = "https://api.alpaca.markets/v2"

    def __init__(self, position_tracker=None):
        self.name             = "BrokerExecutor"
        self.position_tracker = position_tracker
        self.paper            = Config.PAPER_TRADING
        logger.info(f"[{self.name}] Mode: {'📄 PAPER' if self.paper else '🔴 LIVE'}")
        if not self.paper:
            logger.warning(f"[{self.name}] ⚠️  LIVE TRADING ENABLED — real money at risk!")

    # ── Main Entry ────────────────────────────────────────────

    async def execute(self, signal: TradingSignal) -> dict:
        """
        Execute a signal as a trade.
        Returns execution result dict.
        """
        if signal.action == SignalAction.HOLD:
            return {"status": "skipped", "reason": "HOLD signal"}

        if self.paper:
            return await self._paper_execute(signal)

        # Route to appropriate broker
        if signal.asset_class == AssetClass.CRYPTO:
            return await self._binance_execute(signal)
        elif signal.asset_class == AssetClass.STOCK:
            return await self._alpaca_execute(signal)
        else:
            logger.warning(f"[{self.name}] Forex live execution not supported yet")
            return await self._paper_execute(signal)

    # ── Paper Execution ───────────────────────────────────────

    async def _paper_execute(self, signal: TradingSignal) -> dict:
        """
        Simulate order fill at entry price.
        Updates PositionTracker with the new position.
        """
        # Calculate position size
        risk_usd  = Config.ACCOUNT_BALANCE * Config.RISK_PER_TRADE
        sl_dist   = abs(signal.entry_price - signal.stop_loss)
        if sl_dist <= 0:
            return {"status": "error", "reason": "SL distance is zero"}

        qty       = risk_usd / sl_dist
        size_usd  = round(qty * signal.entry_price, 2)

        result = {
            "status":     "filled",
            "mode":       "paper",
            "signal_id":  signal.signal_id,
            "symbol":     signal.asset,
            "side":       signal.action.value,
            "entry":      signal.entry_price,
            "qty":        round(qty, 6),
            "size_usd":   size_usd,
            "tp":         signal.take_profit,
            "sl":         signal.stop_loss,
            "filled_at":  datetime.utcnow().isoformat(),
        }

        if self.position_tracker:
            self.position_tracker.open_position(
                signal_id   = signal.signal_id,
                symbol      = signal.asset,
                action      = signal.action.value,
                entry       = signal.entry_price,
                tp          = signal.take_profit,
                sl          = signal.stop_loss,
                size_usd    = size_usd,
            )

        logger.success(
            f"[{self.name}] 📄 PAPER FILL: {signal.action.value} {signal.asset} "
            f"@ {signal.entry_price:.4f} | qty={qty:.4f} | ${size_usd:.0f}"
        )
        return result

    # ── Binance Testnet / Live ────────────────────────────────

    async def _binance_execute(self, signal: TradingSignal) -> dict:
        """Execute on Binance (testnet or live)."""
        api_key    = Config.BINANCE_API_KEY
        api_secret = Config.BINANCE_SECRET_KEY
        if not api_key or not api_secret:
            logger.warning(f"[{self.name}] Binance keys not set — falling back to paper")
            return await self._paper_execute(signal)

        base_url = self.BINANCE_TESTNET if Config.PAPER_TRADING else self.BINANCE_LIVE

        # Convert BTC-USD → BTCUSDT
        bn_symbol = signal.asset.replace("-USD", "USDT").replace("-", "")
        side      = "BUY" if signal.action == SignalAction.BUY else "SELL"

        # Quantity: risk / SL distance
        risk_usd = Config.ACCOUNT_BALANCE * Config.RISK_PER_TRADE
        sl_dist  = abs(signal.entry_price - signal.stop_loss)
        qty      = round(risk_usd / sl_dist, 5) if sl_dist > 0 else 0.001

        params = {
            "symbol":      bn_symbol,
            "side":        side,
            "type":        "MARKET",
            "quantity":    qty,
            "timestamp":   int(time.time() * 1000),
            "recvWindow":  5000,
        }

        query  = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        sig    = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        query += f"&signature={sig}"

        headers = {"X-MBX-APIKEY": api_key}
        url     = f"{base_url}/v3/order?{query}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as r:
                    data = await r.json()
                    if r.status == 200:
                        logger.success(
                            f"[{self.name}] ✅ Binance order filled: "
                            f"{side} {bn_symbol} orderId={data.get('orderId')}"
                        )
                        return {"status": "filled", "mode": "binance",
                                "order_id": data.get("orderId"), "data": data}
                    else:
                        logger.error(f"[{self.name}] Binance error: {data}")
                        return {"status": "error", "reason": str(data)}
        except Exception as e:
            logger.error(f"[{self.name}] Binance execute failed: {e}")
            return {"status": "error", "reason": str(e)}

    # ── Alpaca Paper / Live ───────────────────────────────────

    async def _alpaca_execute(self, signal: TradingSignal) -> dict:
        """Execute on Alpaca for US stocks."""
        api_key    = Config.ALPACA_API_KEY
        api_secret = Config.ALPACA_SECRET_KEY
        if not api_key or not api_secret:
            logger.warning(f"[{self.name}] Alpaca keys not set — falling back to paper")
            return await self._paper_execute(signal)

        base_url = self.ALPACA_PAPER   # Always paper unless explicitly live
        side     = "buy" if signal.action == SignalAction.BUY else "sell"

        risk_usd = Config.ACCOUNT_BALANCE * Config.RISK_PER_TRADE
        sl_dist  = abs(signal.entry_price - signal.stop_loss)
        qty      = max(1, int(risk_usd / sl_dist)) if sl_dist > 0 else 1

        payload = {
            "symbol":       signal.asset,
            "qty":          qty,
            "side":         side,
            "type":         "market",
            "time_in_force": "day",
        }

        headers = {
            "APCA-API-KEY-ID":     api_key,
            "APCA-API-SECRET-KEY": api_secret,
            "Content-Type":        "application/json",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{base_url}/orders",
                    json=payload, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as r:
                    data = await r.json()
                    if r.status in (200, 201):
                        logger.success(
                            f"[{self.name}] ✅ Alpaca order: "
                            f"{side.upper()} {signal.asset} x{qty} id={data.get('id')}"
                        )
                        return {"status": "filled", "mode": "alpaca",
                                "order_id": data.get("id"), "data": data}
                    else:
                        logger.error(f"[{self.name}] Alpaca error: {data}")
                        return {"status": "error", "reason": str(data)}
        except Exception as e:
            logger.error(f"[{self.name}] Alpaca execute failed: {e}")
            return {"status": "error", "reason": str(e)}
