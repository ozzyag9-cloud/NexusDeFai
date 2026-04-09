"""
NEXUS AI - Live Price Feed (WebSocket)
Streams real-time prices from Binance public WebSocket.
Falls back to yfinance polling for non-crypto symbols.
Provides an in-memory price cache used by the orchestrator for fresher entry prices.
"""

import asyncio
import json
import aiohttp
from datetime import datetime
from loguru import logger
from config import Config, AssetClass


# Binance symbol mapping: yfinance format → Binance stream format
def to_binance_symbol(symbol: str) -> str | None:
    """Convert BTC-USD → btcusdt for Binance stream."""
    if symbol.endswith("-USD"):
        base = symbol.replace("-USD", "").lower()
        return f"{base}usdt"
    return None


class LivePriceFeed:
    """
    Maintains a real-time price cache for all watched symbols.

    Crypto: streams from Binance combined WebSocket (free, no API key needed)
    Stocks/Forex: polled via yfinance every 60s (no WebSocket available free)
    """

    BINANCE_WS = "wss://stream.binance.com:9443/stream?streams="
    RECONNECT_DELAY = 5   # seconds before reconnect on error

    def __init__(self):
        self.name   = "LivePriceFeed"
        self._cache: dict[str, dict] = {}   # symbol → {price, bid, ask, volume, ts}
        self._running = False

    def get_price(self, symbol: str) -> float | None:
        """Get latest cached price for a symbol."""
        entry = self._cache.get(symbol)
        return entry["price"] if entry else None

    def get_snapshot(self, symbol: str) -> dict | None:
        """Full price snapshot with bid/ask and timestamp."""
        return self._cache.get(symbol)

    def get_all(self) -> dict:
        """All cached prices."""
        return dict(self._cache)

    # ── Binance WebSocket ─────────────────────────────────────

    async def _run_binance_ws(self):
        """Stream mini-ticker prices for all crypto symbols."""
        crypto_syms = [s for s in Config.CRYPTO_WATCHLIST]
        streams = [
            f"{to_binance_symbol(s)}@miniTicker"
            for s in crypto_syms
            if to_binance_symbol(s)
        ]
        if not streams:
            return

        url = self.BINANCE_WS + "/".join(streams)
        logger.info(f"[{self.name}] Connecting Binance WS ({len(streams)} streams)")

        while self._running:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(url, heartbeat=20) as ws:
                        logger.success(f"[{self.name}] Binance WS connected")
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = json.loads(msg.data)
                                stream = data.get("stream", "")
                                tick   = data.get("data", {})
                                # Resolve back to our symbol
                                bn_sym = stream.split("@")[0].upper()  # e.g. BTCUSDT
                                for our_sym in crypto_syms:
                                    if to_binance_symbol(our_sym) and \
                                       to_binance_symbol(our_sym).upper() == bn_sym:
                                        self._cache[our_sym] = {
                                            "price":  float(tick.get("c", 0)),
                                            "high":   float(tick.get("h", 0)),
                                            "low":    float(tick.get("l", 0)),
                                            "volume": float(tick.get("v", 0)),
                                            "ts":     datetime.utcnow().isoformat(),
                                        }
                                        break
                            elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                                break
            except Exception as e:
                logger.warning(f"[{self.name}] Binance WS error: {e}")
            if self._running:
                logger.info(f"[{self.name}] Reconnecting in {self.RECONNECT_DELAY}s…")
                await asyncio.sleep(self.RECONNECT_DELAY)

    # ── yFinance poller for stocks/forex ──────────────────────

    async def _poll_non_crypto(self):
        """Poll stock and forex prices every 60s via yfinance."""
        import yfinance as yf
        non_crypto = Config.STOCKS_WATCHLIST + Config.FOREX_WATCHLIST
        logger.info(f"[{self.name}] yFinance polling {len(non_crypto)} symbols")

        while self._running:
            for symbol in non_crypto:
                try:
                    t     = yf.Ticker(symbol)
                    price = float(t.fast_info.last_price)
                    self._cache[symbol] = {
                        "price":  price,
                        "high":   float(t.fast_info.year_high or price),
                        "low":    float(t.fast_info.year_low or price),
                        "volume": float(t.fast_info.three_month_average_volume or 0),
                        "ts":     datetime.utcnow().isoformat(),
                    }
                except Exception as e:
                    logger.debug(f"[{self.name}] poll {symbol}: {e}")
            await asyncio.sleep(60)

    # ── Lifecycle ─────────────────────────────────────────────

    async def start(self):
        """Start all price feed tasks."""
        self._running = True
        asyncio.create_task(self._run_binance_ws())
        asyncio.create_task(self._poll_non_crypto())
        logger.success(f"[{self.name}] Live price feed started")

    async def stop(self):
        self._running = False
        logger.info(f"[{self.name}] Stopped")


# Singleton — shared across the system
price_feed = LivePriceFeed()
