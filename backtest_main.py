#!/usr/bin/env python3
"""
Backtesting entry point — runs the strategy against historical CSV data.

CSV files: one per year, placed in a folder.
  Supported formats: MT4 export, MT5 export, generic OHLCV CSV.

Usage:
  python backtest_main.py --data ./data/EURUSD
  python backtest_main.py --data ./data/EURUSD --timeframe H1
  python backtest_main.py --data ./data/GBPUSD --instrument GBPUSD --from 2020 --to 2024
  python backtest_main.py --data ./data/EURUSD --export results.csv
"""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console

load_dotenv()

from config import settings
from backtest.engine import BacktestEngine
from backtest.report import print_report, export_csv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Master Trader — Backtest Mode",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
CSV Format (auto-detected):
  MT4 : Date,Time,Open,High,Low,Close,Volume
        2020.01.02,00:01,1.12100,1.12150,...
  MT5 : <DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>...
        2020.01.02\t00:01\t1.12100\t1.12150\t...
  Generic : datetime,open,high,low,close,volume
            2020-01-02 00:01:00,1.12100,...

Examples:
  python backtest_main.py --data ./data/EURUSD
  python backtest_main.py --data ./data/EURUSD --tf H1 --from 2020 --to 2023
  python backtest_main.py --data ./data/GBPUSD --instrument GBPUSD --export gbp_results.csv
        """,
    )
    parser.add_argument(
        "--data", "-d",
        required=True,
        help="Path to folder containing yearly CSV files",
    )
    parser.add_argument(
        "--instrument", "-i",
        default=settings.instrument,
        help=f"Instrument name (default: {settings.instrument})",
    )
    parser.add_argument(
        "--tf", "--timeframe",
        default=settings.timeframe,
        choices=["M5", "M15", "M30", "H1", "H4"],
        help=f"Analysis timeframe (default: {settings.timeframe})",
    )
    parser.add_argument(
        "--from", dest="year_from",
        type=int, default=None,
        help="Start year filter (e.g. 2020)",
    )
    parser.add_argument(
        "--to", dest="year_to",
        type=int, default=None,
        help="End year filter (e.g. 2023)",
    )
    parser.add_argument(
        "--sl",
        type=int,
        default=settings.stop_loss_pips,
        help=f"Stop loss in pips (default: {settings.stop_loss_pips})",
    )
    parser.add_argument(
        "--tp",
        type=int,
        default=settings.take_profit_pips,
        help=f"Take profit in pips (default: {settings.take_profit_pips})",
    )
    parser.add_argument(
        "--lot",
        type=float,
        default=settings.mt5_lot_size,
        help=f"Lot size (default: {settings.mt5_lot_size})",
    )
    parser.add_argument(
        "--export", "-e",
        default=None,
        help="Export trades to CSV file (e.g. results.csv)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # Validate data folder
    data_path = Path(args.data)
    if not data_path.exists():
        print(f"ERROR: Data folder not found: {data_path}")
        print("Create the folder and put your yearly CSV files inside it.")
        print("Example: ./data/EURUSD/EURUSD_2020_M1.csv")
        return 1

    # Override settings
    settings.instrument = args.instrument
    settings.timeframe = args.tf
    settings.stop_loss_pips = args.sl
    settings.take_profit_pips = args.tp
    settings.mt5_lot_size = args.lot

    console = Console()
    console.print(
        f"\n[bold cyan]Master Trader — Backtest Mode[/bold cyan]\n"
        f"  Instrument : [green]{args.instrument}[/green]\n"
        f"  Timeframe  : [green]{args.tf}[/green]\n"
        f"  SL / TP    : [yellow]{args.sl}[/yellow] / [yellow]{args.tp}[/yellow] pips  "
        f"(R:R = 1:{args.tp // args.sl})\n"
        f"  Lot size   : {args.lot}\n"
        f"  Data folder: {data_path.resolve()}\n"
    )
    if args.year_from or args.year_to:
        fr = args.year_from or "start"
        to = args.year_to or "end"
        console.print(f"  Year filter: {fr} → {to}\n")

    engine = BacktestEngine(settings=settings, console=console)

    try:
        results = engine.run(
            data_folder=str(data_path),
            instrument=args.instrument,
            timeframe=args.tf,
            year_start=args.year_from,
            year_end=args.year_to,
        )
    except FileNotFoundError as exc:
        console.print(f"[red]ERROR: {exc}[/red]")
        return 1
    except Exception as exc:
        console.print(f"[red]FATAL: {exc}[/red]")
        import traceback
        traceback.print_exc()
        return 1

    print_report(results, console)

    if args.export:
        export_csv(results, args.export)

    return 0


if __name__ == "__main__":
    sys.exit(main())
