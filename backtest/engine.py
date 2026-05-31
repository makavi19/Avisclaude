"""
Backtesting engine — replays historical data through the signal pipeline.

Flow for each analysis bar:
  1. Get last 200 resampled bars
  2. Compute indicators (pure numpy — no Claude)
  3. Generate signal (mirrors agent rules)
  4. If confirmed: open trade on next 1-min bar's open
  5. Walk subsequent 1-min bars: check SL/TP/trailing each bar
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeRemainingColumn

from backtest.data_loader import load_data_folder, resample_to_timeframe
from backtest.signals import analyze_market, select_strategy, confirm_trade, compute_entry_levels
from backtest.sim_broker import SimBroker, BacktestTrade
from backtest.results import BacktestResults
from config import Settings


_TF_MINUTES = {
    "M5": 5, "M15": 15, "M30": 30,
    "H1": 60, "H4": 240, "D1": 1440,
}

# Number of resampled bars needed for indicators
_LOOKBACK = 210


class BacktestEngine:
    def __init__(self, settings: Settings, console: Console | None = None):
        self.settings = settings
        self.console = console or Console()

    def run(
        self,
        data_folder: str,
        instrument: str,
        timeframe: str,
        year_start: int | None = None,
        year_end: int | None = None,
        max_one_trade_per_bar: bool = True,
    ) -> BacktestResults:
        """
        Main entry point.
        Returns a BacktestResults object with all closed trades and stats.
        """
        self.console.print(
            f"\n[bold cyan]Backtesting[/bold cyan] {instrument} {timeframe}\n"
            f"  Loading CSV data from: [green]{data_folder}[/green]"
        )

        # ── Load data ──────────────────────────────────────────────────────────
        df_1m = load_data_folder(data_folder, instrument, year_start, year_end)
        self.console.print(
            f"  Total 1-min bars loaded: [bold]{len(df_1m):,}[/bold]  "
            f"({df_1m.index[0]:%Y-%m-%d} → {df_1m.index[-1]:%Y-%m-%d})"
        )

        # ── Resample to analysis timeframe ─────────────────────────────────────
        df_tf = resample_to_timeframe(df_1m, timeframe)
        self.console.print(
            f"  Resampled to {timeframe}: [bold]{len(df_tf):,}[/bold] bars\n"
        )

        # ── Build result object ────────────────────────────────────────────────
        results = BacktestResults(
            instrument=instrument,
            timeframe=timeframe,
            date_from=df_1m.index[0].to_pydatetime(),
            date_to=df_1m.index[-1].to_pydatetime(),
            lot_size=self.settings.mt5_lot_size,
        )

        broker = SimBroker(
            instrument=instrument,
            sl_pips=self.settings.stop_loss_pips,
            tp_pips=self.settings.take_profit_pips,
            trailing_distance_pips=self.settings.trailing_distance_pips,
            breakeven_trigger_pips=self.settings.breakeven_trigger_pips,
            lot_size=self.settings.mt5_lot_size,
        )

        tf_index = df_tf.index.to_list()
        n_bars = len(tf_index)

        # ── Main loop ─────────────────────────────────────────────────────────
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[bold]{task.completed}/{task.total}[/bold] bars"),
            TimeRemainingColumn(),
            console=self.console,
            transient=True,
        ) as progress:
            task = progress.add_task("Running backtest...", total=n_bars - _LOOKBACK)

            for i in range(_LOOKBACK, n_bars):
                # Slice of analysis bars for indicator computation
                window = df_tf.iloc[i - _LOOKBACK : i]
                closes = window["close"].tolist()
                highs = window["high"].tolist()
                lows = window["low"].tolist()

                current_bar_time = tf_index[i]

                # ── Update open trade with 1-min bars in this tf bar ──────────
                if broker.open_trade is not None:
                    # Get all 1-min bars that fall in the current tf bar
                    tf_minutes = _TF_MINUTES.get(timeframe.upper(), 15)
                    bar_start = current_bar_time
                    bar_end = bar_start + timedelta(minutes=tf_minutes)
                    minute_bars = df_1m[
                        (df_1m.index >= bar_start) & (df_1m.index < bar_end)
                    ]
                    for _, mb in minute_bars.iterrows():
                        closed_trade = broker.update_bar({
                            "datetime": mb.name.to_pydatetime(),
                            "open": mb["open"],
                            "high": mb["high"],
                            "low": mb["low"],
                            "close": mb["close"],
                        })
                        if closed_trade:
                            results.trades.append(closed_trade)
                            break

                # ── Signal generation (only if no open trade) ─────────────────
                if broker.open_trade is None:
                    market = analyze_market(closes, highs, lows, instrument)
                    market["instrument"] = instrument
                    strategy = select_strategy(market)

                    if strategy and confirm_trade(strategy, market):
                        levels = compute_entry_levels(
                            instrument=instrument,
                            direction=strategy["direction"],
                            entry_price=closes[-1],
                            sl_pips=self.settings.stop_loss_pips,
                            tp_pips=self.settings.take_profit_pips,
                        )

                        # Fill on the NEXT 1-min bar's open after the tf bar
                        tf_minutes = _TF_MINUTES.get(timeframe.upper(), 15)
                        fill_time = current_bar_time + timedelta(minutes=tf_minutes)
                        fill_bars = df_1m[df_1m.index >= fill_time].head(1)
                        if fill_bars.empty:
                            progress.advance(task)
                            continue

                        fill_bar = fill_bars.iloc[0]
                        entry_dict = {
                            "datetime": fill_bars.index[0].to_pydatetime(),
                            "open": fill_bar["open"],
                        }

                        broker.try_open(
                            entry_bar=entry_dict,
                            direction=strategy["direction"],
                            stop_loss=levels["stop_loss"],
                            take_profit=levels["take_profit"],
                            strategy_type=strategy["strategy_type"],
                        )

                progress.advance(task)

        # Close any trade still open at the end of data
        if broker.open_trade and not df_1m.empty:
            last_bar = df_1m.iloc[-1]
            closed = broker.force_close(
                {
                    "datetime": df_1m.index[-1].to_pydatetime(),
                    "open": last_bar["open"],
                    "high": last_bar["high"],
                    "low": last_bar["low"],
                    "close": last_bar["close"],
                },
                reason="end_of_data",
            )
            if closed:
                results.trades.append(closed)

        results.trades.extend(broker.closed_trades)
        # Deduplicate (already added above for closed_trade)
        seen = set()
        unique = []
        for t in results.trades:
            if t.trade_id not in seen:
                seen.add(t.trade_id)
                unique.append(t)
        results.trades = sorted(unique, key=lambda t: t.entry_time or datetime.min)
        results.build_equity_curve()

        return results
