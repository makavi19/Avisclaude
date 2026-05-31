"""
Backtest results — trade tracking and performance statistics.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np

from backtest.sim_broker import BacktestTrade


@dataclass
class BacktestResults:
    instrument: str
    timeframe: str
    date_from: datetime
    date_to: datetime
    initial_balance: float = 10_000.0
    lot_size: float = 0.01
    pip_value_usd: float = 1.0   # per 0.01 lot for a USD pair

    trades: list[BacktestTrade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)  # after each trade

    # ── Computed stats ────────────────────────────────────────────────────────

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def winning_trades(self) -> list[BacktestTrade]:
        return [t for t in self.trades if t.pnl_pips > 0]

    @property
    def losing_trades(self) -> list[BacktestTrade]:
        return [t for t in self.trades if t.pnl_pips <= 0]

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        return len(self.winning_trades) / len(self.trades)

    @property
    def total_pips(self) -> float:
        return sum(t.pnl_pips for t in self.trades)

    @property
    def avg_win_pips(self) -> float:
        wins = self.winning_trades
        return sum(t.pnl_pips for t in wins) / len(wins) if wins else 0.0

    @property
    def avg_loss_pips(self) -> float:
        losses = self.losing_trades
        return sum(t.pnl_pips for t in losses) / len(losses) if losses else 0.0

    @property
    def profit_factor(self) -> float:
        gross_profit = sum(t.pnl_pips for t in self.winning_trades)
        gross_loss = abs(sum(t.pnl_pips for t in self.losing_trades))
        return round(gross_profit / gross_loss, 2) if gross_loss > 0 else float("inf")

    @property
    def max_drawdown_pips(self) -> float:
        if not self.equity_curve:
            return 0.0
        curve = np.array(self.equity_curve)
        peak = np.maximum.accumulate(curve)
        drawdown = peak - curve
        return float(np.max(drawdown))

    @property
    def max_consecutive_losses(self) -> int:
        best = 0
        current = 0
        for t in self.trades:
            if t.pnl_pips <= 0:
                current += 1
                best = max(best, current)
            else:
                current = 0
        return best

    @property
    def max_consecutive_wins(self) -> int:
        best = 0
        current = 0
        for t in self.trades:
            if t.pnl_pips > 0:
                current += 1
                best = max(best, current)
            else:
                current = 0
        return best

    @property
    def risk_reward_actual(self) -> float:
        if not self.winning_trades or not self.losing_trades:
            return 0.0
        return round(abs(self.avg_win_pips / self.avg_loss_pips), 2)

    def by_strategy(self) -> dict[str, dict]:
        groups: dict[str, list[BacktestTrade]] = defaultdict(list)
        for t in self.trades:
            groups[t.strategy_type].append(t)
        result = {}
        for st, tlist in groups.items():
            wins = [t for t in tlist if t.pnl_pips > 0]
            result[st] = {
                "count": len(tlist),
                "win_rate": round(len(wins) / len(tlist), 2),
                "total_pips": round(sum(t.pnl_pips for t in tlist), 1),
            }
        return result

    def by_month(self) -> dict[str, dict]:
        groups: dict[str, list[BacktestTrade]] = defaultdict(list)
        for t in self.trades:
            if t.entry_time:
                key = t.entry_time.strftime("%Y-%m")
                groups[key].append(t)
        result = {}
        for month in sorted(groups):
            tlist = groups[month]
            wins = [t for t in tlist if t.pnl_pips > 0]
            result[month] = {
                "trades": len(tlist),
                "wins": len(wins),
                "pips": round(sum(t.pnl_pips for t in tlist), 1),
            }
        return result

    def build_equity_curve(self) -> list[float]:
        """Builds pip-based equity curve after each trade."""
        balance = 0.0
        curve = [balance]
        for t in self.trades:
            balance += t.pnl_pips
            curve.append(round(balance, 2))
        self.equity_curve = curve
        return curve
