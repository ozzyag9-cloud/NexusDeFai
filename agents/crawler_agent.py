"""
NEXUS AI - Agent 1: Data Crawler
Fetches OHLCV candle data from yfinance and news headlines from RSS feeds.
Runs on a schedule; outputs clean DataFrames saved to the data layer.
"""

import asyncio
import aiohttp
import feedparser
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from loguru import logger
from typing import Optional
from config import Config, AssetClass

# RSS news feeds for sentiment
NEWS_FEEDS = {
    "crypto": [
        "https://cointelegraph.com/rss",
        "https://decrypt.co/feed",
        "https://coindesk.com/arc/outboundfeeds/rss/",
    ],
    "stock": [
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=NVDA,AAPL,TSLA&region=US&lang=en-US",
        "https://www.investing.com/rss/news.rss",
    ],
    "forex": [
        "https://www.forexfactory.com/ff_calendar_thisweek.xml",
        "https://www.dailyfx.com/feeds/forex-market-news",
    ],
}


class DataCrawlerAgent:
    """
    Agent 1: Crawls price data + news for all watchlist symbols.
    Returns structured data dict ready for downstream agents.
    """

    def __init__(self):
        self.name = "CrawlerAgent"
        logger.info(f"[{self.name}] Initialized")

    # ── Price Data ────────────────────────────────────────────

    def fetch_ohlcv(
        self,
        symbol: str,
        period: str = "60d",
        interval: str = "1h"
    ) -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV candles via yfinance.
        Returns DataFrame with columns: Open, High, Low, Close, Volume
        """
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, interval=interval)
            if df.empty:
                logger.warning(f"[{self.name}] No data for {symbol}")
                return None

            df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
            df.dropna(inplace=True)
            df.index = pd.to_datetime(df.index, utc=True)
            logger.success(f"[{self.name}] {symbol}: {len(df)} candles fetched")
            return df

        except Exception as e:
            logger.error(f"[{self.name}] fetch_ohlcv({symbol}): {e}")
            return None

    def fetch_multi_timeframe(self, symbol: str) -> dict:
        """
        Fetch 15m, 1h, 4h and daily candles for a symbol.
        Used by strategy agent for multi-timeframe analysis.
        """
        frames = {}
        specs = [
            ("15m", "7d",  "15m"),
            ("1h",  "30d", "1h"),
            ("4h",  "60d", "4h"),   # yfinance returns 1h; we resample to 4h
            ("1d",  "365d","1d"),
        ]
        for label, period, interval in specs:
            df = self.fetch_ohlcv(symbol, period=period, interval=interval)
            if df is not None:
                if label == "4h":
                    df = self._resample_4h(df)
                frames[label] = df
        return frames

    def _resample_4h(self, df: pd.DataFrame) -> pd.DataFrame:
        """Resample 1h candles into 4h candles."""
        return df.resample("4h").agg({
            "Open":   "first",
            "High":   "max",
            "Low":    "min",
            "Close":  "last",
            "Volume": "sum",
        }).dropna()

    def get_current_price(self, symbol: str) -> Optional[float]:
        """Fast current price fetch."""
        try:
            t = yf.Ticker(symbol)
            info = t.fast_info
            return float(info.last_price)
        except Exception as e:
            logger.error(f"[{self.name}] get_current_price({symbol}): {e}")
            return None

    # ── News Headlines ────────────────────────────────────────

    async def fetch_news_headlines(self, asset_class: AssetClass) -> list[dict]:
        """
        Async fetch of news headlines from RSS feeds.
        Returns list of {title, summary, published, source} dicts.
        """
        key = asset_class.value
        feeds = NEWS_FEEDS.get(key, [])
        headlines = []

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        ) as session:
            for url in feeds:
                try:
                    async with session.get(url) as resp:
                        content = await resp.text()
                    parsed = feedparser.parse(content)
                    for entry in parsed.entries[:10]:
                        headlines.append({
                            "title":     entry.get("title", ""),
                            "summary":   entry.get("summary", "")[:300],
                            "published": entry.get("published", ""),
                            "source":    parsed.feed.get("title", url),
                        })
                except Exception as e:
                    logger.warning(f"[{self.name}] RSS feed {url}: {e}")

        logger.info(f"[{self.name}] Fetched {len(headlines)} headlines ({key})")
        return headlines

    # ── Main Crawl Cycle ──────────────────────────────────────

    async def crawl_all(self) -> dict:
        """
        Full crawl cycle: price data + news for all watchlist symbols.
        Returns structured data dict consumed by downstream agents.
        """
        logger.info(f"[{self.name}] ── Starting crawl cycle ──")
        data = {}

        for symbol in Config.all_symbols():
            asset_class = Config.classify(symbol)
            frames = self.fetch_multi_timeframe(symbol)
            price  = self.get_current_price(symbol)

            data[symbol] = {
                "asset_class": asset_class,
                "current_price": price,
                "ohlcv": frames,
                "crawled_at": datetime.utcnow(),
            }

        # Fetch news per asset class
        for ac in [AssetClass.CRYPTO, AssetClass.STOCK, AssetClass.FOREX]:
            headlines = await self.fetch_news_headlines(ac)
            for symbol in Config.all_symbols():
                if Config.classify(symbol) == ac:
                    data[symbol]["headlines"] = headlines

        logger.success(f"[{self.name}] ── Crawl complete: {len(data)} symbols ──")
        return data


if __name__ == "__main__":
    agent = DataCrawlerAgent()
    result = asyncio.run(agent.crawl_all())
    for sym, d in result.items():
        price = d.get("current_price")
        frames = list(d.get("ohlcv", {}).keys())
        print(f"{sym:15s}  ${price}  frames={frames}")
