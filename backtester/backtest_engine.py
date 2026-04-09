"""
NEXUS AI - Backtesting Engine
Vectorized backtest that replays historical data through the full signal pipeline.
Produces equity curve, win rate, Sharpe ratio, max drawdown, and per-trade log.
"""

import asyncio
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional
from loguru import logger
from config import Config, AssetClass, SignalAction
from agents.technical_agent import TechnicalAgent
from agents.strategy_agent  import StrategyEngine
from agents.risk_agent       import RiskAgent


@dataclass
class BacktestTrade:
    signal_id:   str
    symbol:      str
    action:      str
    entry_price: float
    take_profit: float
    stop_loss:   float
    entry_idx:   int
    exit_idx:    Optional[int]   = None
    exit_price:  Optional[float] = None
    outcome:     str = "open"     # tp_hit | sl_hit | expired
    pnl_pct:     float = 0.0
    pnl_usd:     float = 0.0
    confidence:  float = 0.0
    strategy:    str = ""
    bars_held:   int = 0


@dataclass
class BacktestResult:
    symbol:         str
    start_date:     str
    end_date:       str
    total_trades:   int = 0
    wins:           int = 0
    losses:         int = 0
    win_rate:       float = 0.0
    avg_rr:         float = 0.0
    sharpe_ratio:   float = 0.0
    max_drawdown:   float = 0.0
    total_return:   float = 0.0
    profit_factor:  float = 0.0
    avg_bars_held:  float = 0.0
    trades:         list = field(default_factory=list)
    equity_curve:   list = field(default_factory=list)


class BacktestEngine:
    """
    Walk-forward backtester.
    Slides a window across historical OHLCV, runs the indicator+strategy stack,
    then forward-simulates each trade to TP or SL.
    """

    def __init__(self):
        self.technical = TechnicalAgent()
        self.strategy  = StrategyEngine()
        self.risk      = RiskAgent()

    def run(
        self,
        symbol: str,
        period: str = "365d",
        interval: str = "1h",
        lookback: int = 100,
        max_hold_bars: int = 48,
        initial_balance: float = 10000.0,
    ) -> BacktestResult:
        """
        Main backtest entry.
        Walks through historical data, generating and simulating trades.
        """
        logger.info(f"[Backtest] Starting {symbol} | {period} | {interval}")

        # 1. Fetch data
        df = self._fetch(symbol, period, interval)
        if df is None or len(df) < lookback + 20:
            logger.error(f"[Backtest] Insufficient data for {symbol}")
            return BacktestResult(symbol=symbol, start_date="N/A", end_date="N/A")

        asset_class = Config.classify(symbol)
        trades: list[BacktestTrade] = []
        balance = initial_balance
        equity_curve = [initial_balance]
        trade_counter = 0

        # 2. Walk-forward loop
        for i in range(lookback, len(df) - max_hold_bars):
            window = df.iloc[:i].copy()

            # Run indicator stack on window
            ind = self.technical.compute(symbol, window, interval)
            if ind is None:
                continue

            # Skip if a trade is already open
            if trades and trades[-1].outcome == "open":
                continue

            # Strategy signal
            result = self.strategy.run_ensemble(
                symbol=symbol,
                ind=ind,
                asset_class=asset_class,
                sentiment_score=0.0,
                higher_tf_bias=0.0,
            )
            action     = result["action"]
            confidence = result["confidence"]

            # Risk levels
            risk = self.risk.compute_levels(
                symbol=symbol,
                action=action,
                ind=ind,
                asset_class=asset_class,
                confidence=confidence,
            )
            if not risk:
                continue

            # Validate
            valid, _ = self.risk.validate_signal(action, risk["risk_reward"], confidence)
            if not valid:
                continue

            trade_counter += 1
            trade = BacktestTrade(
                signal_id   = f"BT{trade_counter:04d}",
                symbol      = symbol,
                action      = action.value,
                entry_price = risk["entry"],
                take_profit = risk["take_profit"],
                stop_loss   = risk["stop_loss"],
                entry_idx   = i,
                confidence  = confidence,
                strategy    = result["strategy_name"],
            )

            # 3. Simulate forward to TP / SL
            future = df.iloc[i:i + max_hold_bars]
            trade = self._simulate_trade(trade, future, balance)
            trades.append(trade)

            # Update balance
            balance += trade.pnl_usd
            equity_curve.append(round(balance, 2))

        # 4. Compute stats
        result = self._compute_stats(
            symbol=symbol,
            df=df,
            trades=trades,
            equity_curve=equity_curve,
            initial_balance=initial_balance,
        )
        self._print_summary(result)
        return result

    def _fetch(self, symbol: str, period: str, interval: str) -> Optional[pd.DataFrame]:
        try:
            t = yf.Ticker(symbol)
            df = t.history(period=period, interval=interval)
            df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
            df.index = pd.to_datetime(df.index, utc=True)
            return df
        except Exception as e:
            logger.error(f"[Backtest] fetch {symbol}: {e}")
            return None

    def _simulate_trade(
        self, trade: BacktestTrade, future: pd.DataFrame, balance: float
    ) -> BacktestTrade:
        """Forward-simulate a trade to TP or SL."""
        is_buy = trade.action == "BUY"
        pos_size = balance * Config.RISK_PER_TRADE / abs(trade.entry_price - trade.stop_loss) * trade.entry_price

        for j, (idx, row) in enumerate(future.iterrows()):
            high  = row["High"]
            low   = row["Low"]

            hit_tp = high >= trade.take_profit if is_buy else low <= trade.take_profit
            hit_sl = low  <= trade.stop_loss   if is_buy else high >= trade.stop_loss

            if hit_sl and hit_tp:
                # Ambiguous bar — assume SL hit first (conservative)
                hit_tp = False

            if hit_tp:
                trade.exit_idx   = trade.entry_idx + j
                trade.exit_price = trade.take_profit
                trade.outcome    = "tp_hit"
                trade.bars_held  = j + 1
                break
            elif hit_sl:
                trade.exit_idx   = trade.entry_idx + j
                trade.exit_price = trade.stop_loss
                trade.outcome    = "sl_hit"
                trade.bars_held  = j + 1
                break

        if trade.outcome == "open":
            trade.outcome    = "expired"
            trade.exit_price = future["Close"].iloc[-1]
            trade.bars_held  = len(future)

        # P&L
        if is_buy:
            trade.pnl_pct = (trade.exit_price - trade.entry_price) / trade.entry_price * 100
        else:
            trade.pnl_pct = (trade.entry_price - trade.exit_price) / trade.entry_price * 100

        trade.pnl_usd = round(pos_size * trade.pnl_pct / 100, 2)
        trade.pnl_pct = round(trade.pnl_pct, 3)
        return trade

    def _compute_stats(
        self,
        symbol: str,
        df: pd.DataFrame,
        trades: list[BacktestTrade],
        equity_curve: list[float],
        initial_balance: float,
    ) -> BacktestResult:
        closed = [t for t in trades if t.outcome != "open"]
        wins   = [t for t in closed if t.outcome == "tp_hit"]
        losses = [t for t in closed if t.outcome == "sl_hit"]

        total    = len(closed)
        win_rate = len(wins) / total * 100 if total > 0 else 0.0

        # Average R:R of wins / losses
        avg_win_pnl  = np.mean([t.pnl_pct for t in wins])   if wins   else 0.0
        avg_loss_pnl = abs(np.mean([t.pnl_pct for t in losses])) if losses else 1.0
        avg_rr = avg_win_pnl / avg_loss_pnl if avg_loss_pnl else 0.0

        # Profit factor
        gross_profit = sum(t.pnl_usd for t in wins)
        gross_loss   = abs(sum(t.pnl_usd for t in losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # Max drawdown
        eq = pd.Series(equity_curve)
        peak = eq.cummax()
        dd   = (eq - peak) / peak * 100
        max_dd = float(dd.min())

        # Sharpe (annualized, assuming 1h bars → 8760 bars/year)
        returns = pd.Series([t.pnl_pct for t in closed])
        sharpe = 0.0
        if len(returns) > 2 and returns.std() > 0:
            bars_per_year = 8760 if "h" in "1h" else 252
            sharpe = float(returns.mean() / returns.std() * np.sqrt(bars_per_year / 48))

        # Total return
        final_balance = equity_curve[-1] if equity_curve else initial_balance
        total_return  = (final_balance - initial_balance) / initial_balance * 100

        return BacktestResult(
            symbol         = symbol,
            start_date     = str(df.index[0].date()),
            end_date       = str(df.index[-1].date()),
            total_trades   = total,
            wins           = len(wins),
            losses         = len(losses),
            win_rate       = round(win_rate, 1),
            avg_rr         = round(avg_rr, 2),
            sharpe_ratio   = round(sharpe, 2),
            max_drawdown   = round(max_dd, 2),
            total_return   = round(total_return, 2),
            profit_factor  = round(profit_factor, 2),
            avg_bars_held  = round(np.mean([t.bars_held for t in closed]), 1) if closed else 0,
            trades         = [t.__dict__ for t in closed],
            equity_curve   = equity_curve,
        )

    def _print_summary(self, r: BacktestResult):
        logger.info(
            f"\n{'═'*50}\n"
            f"  BACKTEST RESULTS — {r.symbol}\n"
            f"  Period: {r.start_date} → {r.end_date}\n"
            f"{'─'*50}\n"
            f"  Trades:        {r.total_trades}\n"
            f"  Win Rate:      {r.win_rate:.1f}%  ({r.wins}W / {r.losses}L)\n"
            f"  Avg R:R:       {r.avg_rr:.2f}:1\n"
            f"  Profit Factor: {r.profit_factor:.2f}\n"
            f"  Total Return:  {r.total_return:+.2f}%\n"
            f"  Max Drawdown:  {r.max_drawdown:.2f}%\n"
            f"  Sharpe Ratio:  {r.sharpe_ratio:.2f}\n"
            f"  Avg Bars Held: {r.avg_bars_held:.1f}\n"
            f"{'═'*50}"
        )

    def run_portfolio(self, symbols: list[str], **kwargs) -> list[BacktestResult]:
        """Backtest multiple symbols and return sorted results."""
        results = []
        for sym in symbols:
            r = self.run(sym, **kwargs)
            results.append(r)
        results.sort(key=lambda x: x.total_return, reverse=True)
        return results


if __name__ == "__main__":
    engine = BacktestEngine()
    result = engine.run("BTC-USD", period="180d", interval="1h")
    print(f"\nBest strategy found: {result.win_rate:.1f}% win rate, "
          f"{result.total_return:+.2f}% total return")
