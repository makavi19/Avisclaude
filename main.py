#!/usr/bin/env python3
"""Master Trader Agent System — Entry Point"""

import argparse
import asyncio
import sys

from dotenv import load_dotenv
from rich.console import Console

load_dotenv()

from config import settings
from utils.logger import configure_logging, get_logger
from agents.master_agent import MasterAgent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Master Trader Agent System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py
  python main.py --instrument GBPUSD --timeframe H1
  python main.py --scenario bearish
  python main.py --scenario news_abort
  python main.py --scenario sideways --instrument EURUSD

Scenarios: bullish, bearish, sideways, reversal_oversold, news_abort
        """,
    )
    parser.add_argument(
        "--instrument",
        default=settings.instrument,
        help=f"Trading instrument (default: {settings.instrument})",
    )
    parser.add_argument(
        "--timeframe",
        default=settings.timeframe,
        help=f"Chart timeframe (default: {settings.timeframe})",
    )
    parser.add_argument(
        "--scenario",
        default=settings.mock_scenario,
        choices=["bullish", "bearish", "sideways", "reversal_oversold", "news_abort"],
        help="Mock market scenario (default: bullish)",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=settings.max_strategy_retries,
        help=f"Max strategy selection retries (default: {settings.max_strategy_retries})",
    )
    return parser.parse_args()


async def main() -> int:
    args = parse_args()

    # Apply overrides
    settings.instrument = args.instrument
    settings.timeframe = args.timeframe
    settings.mock_scenario = args.scenario
    settings.max_strategy_retries = args.retries

    configure_logging(settings.log_file, settings.log_level)
    logger = get_logger("main")

    if not settings.anthropic_api_key:
        console = Console()
        console.print(
            "[red]ERROR: ANTHROPIC_API_KEY is not set. "
            "Copy .env.example to .env and add your key.[/red]"
        )
        return 1

    console = Console()
    console.print(
        f"\n[bold cyan]Master Trader Agent System[/bold cyan]\n"
        f"  Instrument : [green]{settings.instrument}[/green]\n"
        f"  Timeframe  : [green]{settings.timeframe}[/green]\n"
        f"  Scenario   : [yellow]{settings.mock_scenario}[/yellow]\n"
        f"  Model      : [dim]{settings.model}[/dim]\n"
        f"  SL / TP    : {settings.stop_loss_pips} pips / {settings.take_profit_pips} pips\n"
    )

    master = MasterAgent(settings=settings, console=console)

    try:
        result = await master.run_pipeline(args.instrument, args.timeframe)
    except KeyboardInterrupt:
        console.print("\n[yellow]Pipeline interrupted by user[/yellow]")
        return 0

    console.print()
    status_colors = {
        "completed": "green",
        "no_go": "yellow",
        "aborted": "red",
    }
    color = status_colors.get(result.pipeline_status, "white")
    console.print(f"[bold]Final Status: [{color}]{result.pipeline_status.upper()}[/{color}][/bold]")

    if result.live_trade:
        t = result.live_trade
        console.print(
            f"\n[bold]Trade Summary[/bold]\n"
            f"  Trade ID  : {t.trade_id}\n"
            f"  Direction : {t.signal.direction.value.upper()}\n"
            f"  Entry     : {t.actual_entry_price}\n"
            f"  SL        : {t.current_sl}\n"
            f"  TP        : {t.current_tp}\n"
            f"  Final PnL : {t.pnl_pips:+.1f} pips\n"
            f"  Status    : {t.status.value}\n"
        )

    if result.error_message:
        console.print(f"[red]Error: {result.error_message}[/red]")

    logger.info(f"Pipeline finished: status={result.pipeline_status}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
