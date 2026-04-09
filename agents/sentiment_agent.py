"""
NEXUS AI - Agent 3: Sentiment Agent
Scores news headlines using TextBlob NLP + optional Claude AI deep analysis.
Returns sentiment float: -1.0 (very bearish) to +1.0 (very bullish).
"""

import asyncio
import os
import json
from textblob import TextBlob
from loguru import logger
from config import Config


class SentimentAgent:
    """
    Agent 3: Scores market sentiment from news headlines.
    Two modes:
      - Fast (TextBlob): keyword + polarity scoring. Free, always available.
      - Deep (Claude AI): nuanced market-aware analysis. Requires ANTHROPIC_API_KEY.
    """

    # Keywords that amplify bullish/bearish scores
    BULLISH_KEYWORDS = {
        "surge", "rally", "breakout", "bullish", "soars", "all-time high",
        "adoption", "partnership", "beats", "record", "upgrade", "buy",
        "accumulate", "moon", "uptrend", "support", "bounce",
    }
    BEARISH_KEYWORDS = {
        "crash", "dump", "bearish", "plunge", "ban", "hack", "exploit",
        "lawsuit", "selloff", "downgrade", "sell", "resistance",
        "liquidation", "regulation", "fear", "warning", "decline",
    }

    def __init__(self):
        self.name = "SentimentAgent"
        self.has_ai = bool(Config.ANTHROPIC_API_KEY)
        mode = "AI-enhanced" if self.has_ai else "TextBlob"
        logger.info(f"[{self.name}] Initialized ({mode} mode)")

    # ── Fast TextBlob Scoring ─────────────────────────────────

    def score_headline(self, text: str) -> float:
        """Score a single headline. Returns -1.0 to +1.0."""
        text_lower = text.lower()

        # TextBlob polarity (-1 to +1)
        blob_score = TextBlob(text).sentiment.polarity

        # Keyword boost
        keyword_boost = 0.0
        for kw in self.BULLISH_KEYWORDS:
            if kw in text_lower:
                keyword_boost += 0.15
        for kw in self.BEARISH_KEYWORDS:
            if kw in text_lower:
                keyword_boost -= 0.15

        raw = blob_score + keyword_boost
        return max(-1.0, min(1.0, raw))

    def score_headlines_batch(
        self, headlines: list[dict], symbol: str = ""
    ) -> float:
        """
        Score a list of headlines for relevance + sentiment.
        Weights recent and symbol-relevant headlines higher.
        Returns aggregate score -1.0 to +1.0.
        """
        if not headlines:
            return 0.0

        symbol_clean = symbol.replace("-USD", "").replace("=X", "").upper()
        scores = []

        for h in headlines:
            text = f"{h.get('title', '')} {h.get('summary', '')}"
            score = self.score_headline(text)

            # Relevance weight: does headline mention the symbol?
            weight = 1.5 if symbol_clean and symbol_clean.lower() in text.lower() else 1.0
            scores.append(score * weight)

        if not scores:
            return 0.0

        avg = sum(scores) / len(scores)
        return round(max(-1.0, min(1.0, avg)), 3)

    # ── AI Deep Sentiment (Claude) ────────────────────────────

    async def deep_sentiment_ai(
        self, headlines: list[dict], symbol: str, current_price: float
    ) -> float:
        """
        Use Claude to perform market-aware sentiment analysis.
        Falls back to TextBlob if API key is not set.
        """
        if not self.has_ai:
            return self.score_headlines_batch(headlines, symbol)

        try:
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=Config.ANTHROPIC_API_KEY)

            headline_text = "\n".join(
                f"- {h['title']}" for h in headlines[:15]
            )

            prompt = (
                f"You are a professional quantitative trader analyzing market sentiment.\n\n"
                f"Asset: {symbol}\n"
                f"Current price: ${current_price:,.4f}\n\n"
                f"Recent headlines:\n{headline_text}\n\n"
                f"Analyze these headlines specifically for their impact on {symbol}. "
                f"Consider market context, macro environment, and trader psychology.\n\n"
                f"Respond ONLY with a JSON object:\n"
                f'{{"score": <float -1.0 to 1.0>, "reasoning": "<1 sentence>", "key_driver": "<main headline>"}}'
            )

            message = await client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}]
            )

            raw = message.content[0].text.strip()
            # Strip markdown code blocks if present
            raw = raw.replace("```json", "").replace("```", "").strip()
            result = json.loads(raw)
            score = float(result.get("score", 0.0))
            reasoning = result.get("reasoning", "")
            logger.info(f"[{self.name}] AI sentiment {symbol}: {score:+.2f} — {reasoning}")
            return max(-1.0, min(1.0, score))

        except Exception as e:
            logger.warning(f"[{self.name}] AI sentiment failed ({e}), using TextBlob")
            return self.score_headlines_batch(headlines, symbol)

    # ── Main Entry ────────────────────────────────────────────

    async def analyze(
        self, symbol: str, headlines: list[dict], current_price: float,
        use_ai: bool = True
    ) -> dict:
        """
        Full sentiment analysis for a symbol.
        Returns dict with score, label, and headline count.
        """
        if use_ai and self.has_ai:
            score = await self.deep_sentiment_ai(headlines, symbol, current_price)
        else:
            score = self.score_headlines_batch(headlines, symbol)

        if score > 0.2:
            label = "Bullish" if score > 0.5 else "Mildly Bullish"
        elif score < -0.2:
            label = "Bearish" if score < -0.5 else "Mildly Bearish"
        else:
            label = "Neutral"

        return {
            "symbol":    symbol,
            "score":     score,
            "label":     label,
            "headlines": len(headlines),
        }


if __name__ == "__main__":
    agent = SentimentAgent()
    test_headlines = [
        {"title": "Bitcoin surges to new all-time high amid institutional adoption", "summary": ""},
        {"title": "Fed signals rate cuts, risk assets rally", "summary": ""},
        {"title": "Crypto exchange faces new regulatory scrutiny", "summary": ""},
    ]
    result = asyncio.run(agent.analyze("BTC-USD", test_headlines, 96000))
    print(result)
