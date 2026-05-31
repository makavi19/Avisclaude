"""
Rich terminal report and CSV export for backtest results.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from backtest.results import BacktestResults


def _color_pips(pips: float) -> str:
    color = "green" if pips > 0 else ("red" if pips < 0 else "dim")
    return f"[{color}]{pips:+.1f}[/{color}]"


def _sparkline(values: list[float], width: int = 40) -> str:
    """ASCII equity curve using block characters."""
    if len(values) < 2:
        return "—"
    blocks = "▁▂▃▄▅▆▇█"
    mn, mx = min(values), max(values)
    rng = mx - mn or 1.0
    # Sample down to `width` points
    step = max(1, len(values) // width)
    sampled = [values[i] for i in range(0, len(values), step)][:width]
    line = ""
    for v in sampled:
        idx = int((v - mn) / rng * (len(blocks) - 1))
        block = blocks[idx]
        color = "green" if v >= 0 else "red"
        line += f"[{color}]{block}[/{color}]"
    return line


def print_report(results: BacktestResults, console: Console | None = None) -> None:
    console = console or Console()
    r = results
    r.build_equity_curve()

    # ── Header ────────────────────────────────────────────────────────────────
    console.print()
    console.print(Panel(
        f"[bold cyan]Backtest Results — {r.instrument} {r.timeframe}[/bold cyan]\n"
        f"Period: [green]{r.date_from:%Y-%m-%d}[/green] → [green]{r.date_to:%Y-%m-%d}[/green]  |  "
        f"Total trades: [bold]{r.total_trades}[/bold]",
        box=box.DOUBLE
    ))

    # ── Summary stats ──────────────────────────────────────────────────────────
    stats = Table(title="Summary Statistics", box=box.ROUNDED, show_header=True)
    stats.add_column("Metric", style="bold")
    stats.add_column("Value", justify="right")

    wr_color = "green" if r.win_rate >= 0.5 else "red"
    pf_color = "green" if r.profit_factor >= 1.2 else "yellow" if r.profit_factor >= 1.0 else "red"

    stats.add_row("Total Trades",           str(r.total_trades))
    stats.add_row("Winning Trades",         f"[green]{len(r.winning_trades)}[/green]")
    stats.add_row("Losing Trades",          f"[red]{len(r.losing_trades)}[/red]")
    stats.add_row("Win Rate",               f"[{wr_color}]{r.win_rate:.1%}[/{wr_color}]")
    stats.add_row("Total Pips",             _color_pips(r.total_pips))
    stats.add_row("Avg Win",                f"[green]+{r.avg_win_pips:.1f} pips[/green]")
    stats.add_row("Avg Loss",               f"[red]{r.avg_loss_pips:.1f} pips[/red]")
    stats.add_row("Actual R:R",             f"{r.risk_reward_actual:.2f}")
    stats.add_row("Profit Factor",          f"[{pf_color}]{r.profit_factor:.2f}[/{pf_color}]")
    stats.add_row("Max Drawdown",           f"[red]-{r.max_drawdown_pips:.1f} pips[/red]")
    stats.add_row("Max Consecutive Wins",   f"[green]{r.max_consecutive_wins}[/green]")
    stats.add_row("Max Consecutive Losses", f"[red]{r.max_consecutive_losses}[/red]")
    stats.add_row("SL / TP (pips)",         "10 / 20  (1:2 R:R)")

    console.print(stats)

    # ── Equity curve ──────────────────────────────────────────────────────────
    curve = r.equity_curve
    if curve:
        final = curve[-1]
        console.print(
            f"\n[bold]Equity Curve[/bold]  "
            f"(0 → [{('green' if final >= 0 else 'red')}]{final:+.1f} pips[/])\n"
            f"{_sparkline(curve, 60)}\n"
        )

    # ── By strategy ───────────────────────────────────────────────────────────
    by_st = r.by_strategy()
    if by_st:
        st_table = Table(title="By Strategy", box=box.ROUNDED)
        st_table.add_column("Strategy")
        st_table.add_column("Trades", justify="right")
        st_table.add_column("Win Rate", justify="right")
        st_table.add_column("Total Pips", justify="right")
        for st, data in sorted(by_st.items(), key=lambda x: -x[1]["total_pips"]):
            wr_col = "green" if data["win_rate"] >= 0.5 else "red"
            st_table.add_row(
                st.replace("_", " ").title(),
                str(data["count"]),
                f"[{wr_col}]{data['win_rate']:.1%}[/{wr_col}]",
                _color_pips(data["total_pips"]),
            )
        console.print(st_table)

    # ── Monthly breakdown ─────────────────────────────────────────────────────
    monthly = r.by_month()
    if monthly:
        mo_table = Table(title="Monthly Breakdown", box=box.ROUNDED)
        mo_table.add_column("Month")
        mo_table.add_column("Trades", justify="right")
        mo_table.add_column("Wins", justify="right")
        mo_table.add_column("W%", justify="right")
        mo_table.add_column("Pips", justify="right")
        for month, data in sorted(monthly.items()):
            wr = data["wins"] / data["trades"] if data["trades"] else 0
            wr_col = "green" if wr >= 0.5 else "red"
            mo_table.add_row(
                month,
                str(data["trades"]),
                str(data["wins"]),
                f"[{wr_col}]{wr:.0%}[/{wr_col}]",
                _color_pips(data["pips"]),
            )
        console.print(mo_table)

    # ── Last 15 trades ────────────────────────────────────────────────────────
    if r.trades:
        last_trades = r.trades[-15:]
        tr_table = Table(title=f"Last {len(last_trades)} Trades", box=box.ROUNDED)
        tr_table.add_column("ID")
        tr_table.add_column("Entry Time")
        tr_table.add_column("Dir")
        tr_table.add_column("Strategy")
        tr_table.add_column("Entry")
        tr_table.add_column("Exit")
        tr_table.add_column("PnL (pips)", justify="right")
        tr_table.add_column("Reason")
        for t in last_trades:
            dir_color = "green" if t.direction == "buy" else "red"
            tr_table.add_row(
                t.trade_id,
                t.entry_time.strftime("%Y-%m-%d %H:%M") if t.entry_time else "—",
                f"[{dir_color}]{t.direction.upper()}[/{dir_color}]",
                t.strategy_type.replace("_", " "),
                f"{t.entry_price:.5f}",
                f"{t.exit_price:.5f}" if t.exit_price else "—",
                _color_pips(t.pnl_pips),
                t.exit_reason or "—",
            )
        console.print(tr_table)


def export_csv(results: BacktestResults, output_path: str) -> None:
    """Export all trades to a CSV file."""
    import csv
    path = Path(output_path)
    rows = []
    for t in results.trades:
        rows.append({
            "trade_id": t.trade_id,
            "instrument": t.instrument,
            "direction": t.direction,
            "strategy_type": t.strategy_type,
            "entry_time": t.entry_time.isoformat() if t.entry_time else "",
            "exit_time": t.exit_time.isoformat() if t.exit_time else "",
            "entry_price": t.entry_price,
            "exit_price": t.exit_price or "",
            "initial_sl": t.initial_sl,
            "take_profit": t.take_profit,
            "pnl_pips": t.pnl_pips,
            "max_pnl_pips": t.max_pnl_pips,
            "exit_reason": t.exit_reason or "",
            "breakeven_activated": t.breakeven_activated,
            "trailing_active": t.trailing_active,
        })
    if rows:
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nTrades exported to: {path}")
