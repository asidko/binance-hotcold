import asyncio
import sys
from statistics import median, mean

import aiohttp
import argparse
from typing import List, Dict, Any, Optional

from rich.console import Console
from rich.table import Table
from rich.progress import Progress, BarColumn, TimeRemainingColumn, TextColumn
from datetime import datetime
from dataclasses import dataclass
import re

# Initialize Rich Console
console = Console()

# Binance Futures API Constants
EXCHANGE_INFO_URL = 'https://fapi.binance.com/fapi/v1/exchangeInfo'
KLINES_URL = 'https://fapi.binance.com/fapi/v1/klines'

# Asynchronous semaphore to limit concurrent requests
MAX_CONCURRENCY = 20
SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENCY)

# Type Definitions
KlineData = List[List[Any]]


@dataclass
class SymbolAnalysisResult:
    category: str  # 'booster', 'loser', or 'neutral'
    symbol: str
    change_percent: float
    change_percent_big_interval: float
    marks: list[str]
    price: float


def parse_percentage(pct_str: str) -> float:
    try:
        return float(pct_str.strip('%'))
    except ValueError:
        console.print("[red]Invalid percentage format. Using default 2%.[/red]")
        return 2.0


def parse_timeframe(timeframe: str) -> int:
    match = re.match(r'^(\d+)([mhd])$', timeframe)
    if not match:
        raise ValueError(f"Invalid timeframe format: {timeframe}")
    value, unit = match.groups()
    multipliers = {'m': 1, 'h': 60, 'd': 1440}  # m -> 1, h -> 60, d -> 1440 (24 * 60)
    return int(value) * multipliers[unit]


def get_small_interval(timeframe: str) -> str:
    total_minutes = parse_timeframe(timeframe)
    if total_minutes <= 60:  # <= 1 hour
        return '1m'
    elif total_minutes <= 240:  # <= 4 hours
        return '15m'
    elif total_minutes <= 1440:  # <= 1 day
        return '1h'
    else:  # > 1 day
        return '4h'


def calculate_required_candles(total_time: str, candle_interval: str) -> int:
    total_minutes = parse_timeframe(total_time)
    candle_minutes = parse_timeframe(candle_interval)
    return max((total_minutes // candle_minutes) + 1, 1)


async def fetch_json(session: aiohttp.ClientSession, url: str, params: Dict[str, Any]) -> Any:
    try:
        async with SEMAPHORE:
            async with session.get(url, params=params, ssl=False, timeout=10) as response:
                if response.status != 200:
                    return None
                return await response.json()
    except Exception:
        return None


async def get_usdt_symbols(session: aiohttp.ClientSession) -> List[str]:
    data = await fetch_json(session, EXCHANGE_INFO_URL, {})
    if data is None:
        return []
    symbols = [s['symbol'] for s in data['symbols'] if s['quoteAsset'] == 'USDT' and s['status'] == 'TRADING']
    return symbols


def calculate_avg_max(candles: KlineData, ratio_to_pick: float) -> float:
    top_x = max(int(len(candles) * ratio_to_pick), 1)
    max_values = [float(candle[2]) for candle in candles]
    top_max = sorted(max_values, reverse=True)[:top_x]
    return sum(top_max) / len(top_max) if top_max else 0.0


def trimmed_median(prices, trim_percent=5):
    trim_count = int(len(prices) * trim_percent / 100)
    return median(sorted(prices)[trim_count: -trim_count or None])


def calculate_avg_min(candles: KlineData, ration_to_pick: float) -> float:
    bottom_x = max(int(len(candles) * ration_to_pick), 1)
    min_values = [float(candle[3]) for candle in candles]
    bottom_min = sorted(min_values)[:bottom_x]
    return sum(bottom_min) / len(bottom_min) if bottom_min else 0.0


async def analyze_symbol_simple(
        session: aiohttp.ClientSession,
        symbol: str,
        args: argparse.Namespace
) -> Optional[SymbolAnalysisResult]:
    try:

        # Get Current interval data
        current_interval = args.current_interval
        current_small_interval = get_small_interval(current_interval)
        current_limit = calculate_required_candles(current_interval, current_small_interval)
        current_data = await fetch_json(session, KLINES_URL, {
            'symbol': symbol,
            'interval': current_small_interval,
            'limit': current_limit
        })
        # Get last candle data
        current_data_last = current_data[-1]
        # Get all previous candles
        current_data = current_data[:-1]
        # Get current price from close price of last candle
        current_price = float(current_data_last[4])

        # Calculate averages of max and min if we have enough data
        if len(current_data) >= 10:
            current_max = calculate_avg_max(current_data, 0.2)
            current_min = calculate_avg_min(current_data, 0.2)
        else:
            current_max = max(float(candle[2]) for candle in current_data)
            current_min = min(float(candle[3]) for candle in current_data)

        is_current_price_satisfied_by_max = current_price > current_max
        is_current_price_satisfied_by_min = current_price < current_min

        # Determine Booster
        if is_current_price_satisfied_by_max:
            category = "booster"
            change_percent = ((current_price - current_max) / current_max) * 100
            price = current_price
        # Determine Loser
        elif is_current_price_satisfied_by_min:
            category = "loser"
            change_percent = ((current_price - current_min) / current_min) * 100
            price = current_price
        else:
            category = "neutral"
            change_percent_up = ((current_price - current_max) / current_max) * 100
            change_percent = change_percent_up
            price = current_price


        return SymbolAnalysisResult(
            category=category,
            symbol=symbol,
            change_percent=change_percent,
            change_percent_big_interval=0.0,
            price=price,
            marks=[]
        )

    except Exception:
        return None


async def analyze_symbol(
        session: aiohttp.ClientSession,
        symbol: str,
        args: argparse.Namespace
) -> Optional[SymbolAnalysisResult]:
    try:
        # Determine small intervals and required candles
        big_interval = args.big_interval
        short_interval = args.short_interval
        current_interval = args.current_interval

        big_small_interval = get_small_interval(big_interval)
        short_small_interval = get_small_interval(short_interval)
        current_small_interval = get_small_interval(current_interval)

        big_limit = calculate_required_candles(big_interval, big_small_interval)
        short_limit = calculate_required_candles(short_interval, short_small_interval)
        current_limit = calculate_required_candles(current_interval, current_small_interval)

        # Fetch candlestick data
        big_data = await fetch_json(session, KLINES_URL, {
            'symbol': symbol,
            'interval': big_small_interval,
            'limit': big_limit
        })
        short_data = await fetch_json(session, KLINES_URL, {
            'symbol': symbol,
            'interval': short_small_interval,
            'limit': short_limit
        })
        current_data = await fetch_json(session, KLINES_URL, {
            'symbol': symbol,
            'interval': current_small_interval,
            'limit': current_limit
        })

        if not (big_data and short_data and current_data):
            return None

        # Calculate averages
        big_max_avg = calculate_avg_max(big_data, args.big_avg_ratio)
        short_max_avg = calculate_avg_max(short_data, args.short_avg_ratio)
        current_max = max(float(candle[2]) for candle in current_data)

        big_min_avg = calculate_avg_min(big_data, args.big_avg_ratio)
        short_min_avg = calculate_avg_min(short_data, args.short_avg_ratio)
        current_min = min(float(candle[3]) for candle in current_data)

        # No spikes check
        if args.no_spikes:
            big_median = trimmed_median([float(candle[4]) for candle in big_data])
            short_close_avg = mean([float(candle[4]) for candle in short_data])
            # Check short data close prices average is not threshold % away from median
            is_valid = abs((short_close_avg - big_median) / big_median) < args.spike_threshold / 100
            # Ignore this symbol
            if not is_valid:
                return None

        # Determine Booster

        # Intervals defined by max values
        is_big_interval_satisfied_by_max = current_max > big_max_avg
        is_short_interval_satisfied_by_max = current_max > short_max_avg

        # Intervals defined by min values
        is_big_interval_satisfied_by_min = current_min < big_min_avg
        is_short_interval_satisfied_by_min = current_min < short_min_avg

        marks = []
        marks += ["›"] if is_short_interval_satisfied_by_max or is_short_interval_satisfied_by_min else []
        marks += ["»"] if is_big_interval_satisfied_by_max or is_big_interval_satisfied_by_min else []

        # Determine Booster
        if is_short_interval_satisfied_by_max and is_big_interval_satisfied_by_max:
            category = "booster"
            change_percent = ((current_max - short_max_avg) / short_max_avg) * 100
            change_percent_big_interval = ((current_max - big_max_avg) / big_max_avg) * 100
            price = current_max
        # Determine Loser
        elif is_short_interval_satisfied_by_min and is_big_interval_satisfied_by_min:
            category = "loser"
            change_percent = ((current_min - short_min_avg) / short_min_avg) * 100
            change_percent_big_interval = ((current_min - big_min_avg) / big_min_avg) * 100
            price = current_min
        else:
            category = "neutral"
            change_percent_up = ((current_max - short_max_avg) / short_max_avg) * 100
            change_percent_down = ((current_min - short_min_avg) / short_min_avg) * 100
            # Determine what's looks better for neutral its gain or loss
            if abs(change_percent_up) >= abs(change_percent_down):
                change_percent = change_percent_up
                change_percent_big_interval = ((current_max - big_max_avg) / big_max_avg) * 100
                price = current_max
            else:
                change_percent = change_percent_down
                change_percent_big_interval = ((current_min - big_min_avg) / big_min_avg) * 100
                price = current_min

        return SymbolAnalysisResult(
            category=category,
            symbol=symbol,
            change_percent=change_percent,
            change_percent_big_interval=change_percent_big_interval,
            price=price,
            marks=marks
        )
    except Exception:
        return None


def create_table_simple(results: List[SymbolAnalysisResult], last_updated: str, args: argparse.Namespace) -> Table:
    top_count = args.count
    current_interval = args.current_interval

    table = Table(title=f"Binance Top {top_count} Boosters and Losers\nUpdated: {last_updated}")
    table.add_column("Symbol Futures", style="cyan", no_wrap=True)
    table.add_column(f"Change on {current_interval}", style="magenta", justify="right")
    table.add_column(f"Current price", style="", justify="right")

    for res in results:
        symbol = res.symbol
        price = res.price
        change = res.change_percent

        if res.category == "booster":
            symbol_display = f"🔥 {symbol}"
            change_display = f"[green]{change:.2f}%[/green]"
            price_display = f"{price:.4f}"
        elif res.category == "loser":
            symbol_display = f"❄️ {symbol}"
            change_display = f"[red]{change:.2f}%[/red]"
            price_display = f"{price:.4f}"
        else:
            symbol_display = f"{symbol}"
            change_display = f"[green]{change:.2f}%[/green]" if change > 0 else f"[red]{change:.2f}%[/red]"
            price_display = f"{price:.4f}"

        table.add_row(symbol_display, change_display, price_display)
    return table


def create_table(results: List[SymbolAnalysisResult], last_updated: str, args: argparse.Namespace) -> Table:
    top_count = args.count
    current_interval = args.current_interval
    big_interval = args.big_interval
    short_interval = args.short_interval

    table = Table(title=f"Binance Top {top_count} Boosters and Losers\nUpdated: {last_updated}")
    table.add_column(f"Symbol Futures on {current_interval}", style="cyan", no_wrap=True)
    table.add_column(f"Change for {short_interval}", style="magenta", justify="right")
    table.add_column(f"Change for {big_interval}", style="magenta", justify="right")
    table.add_column(f"Price {current_interval}", style="", justify="right")

    for res in results:
        symbol = res.symbol
        price = res.price
        change = res.change_percent
        change_big_interval = res.change_percent_big_interval

        marks = "".join(res.marks)
        marks_display = f" [yellow]{marks}[/yellow]" if res.marks else ""

        if res.category == "booster":
            symbol_display = f"🚀 {symbol}{marks_display}"
            change_display = f"[red]{change:.2f}%[/red]" if change < 0 else f"[green]{change:.2f}%[/green]"
            change_big_interval_display = f"[green]{change_big_interval:.2f}%[/green]" if change_big_interval > 0 else f"[red]{change_big_interval:.2f}%[/red]"
            price_display = f"{price:.4f}"
        elif res.category == "loser":
            symbol_display = f"🍂 {symbol}{marks_display}"
            change_display = f"[red]{change:.2f}%[/red]" if change < 0 else f"[green]{change:.2f}%[/green]"
            change_big_interval_display = f"[red]{change_big_interval:.2f}%[/red]" if change_big_interval < 0 else f"[green]{change_big_interval:.2f}%[/green]"
            price_display = f"{price:.4f}"
        else:
            symbol_display = f"🌊 {symbol}{marks_display}"
            change_display = f"[red]{change:.2f}%[/red]" if change < 0 else f"[green]{change:.2f}%[/green]"
            change_big_interval_display = f"[red]{change_big_interval:.2f}%[/red]" if change_big_interval < 0 else f"[green]{change_big_interval:.2f}%[/green]"
            price_display = f"{price:.4f}"

        table.add_row(symbol_display, change_display, change_big_interval_display, price_display)
    return table


async def main(args: argparse.Namespace):
    # Human-readable message
    if args.simple:
        console.print(
            f"\n[bold]Searching where the current price is different on last [yellow]{args.current_interval}[/yellow] interval[/bold]\n")
    else:
        console.print(
        f"\n[bold]Searching where the last [yellow]{args.current_interval}[/yellow] price is different on last [yellow]{args.short_interval}[/yellow] and [yellow]{args.big_interval}[/yellow] intervals[/bold]\n")

    async with aiohttp.ClientSession() as session:
        # Fetching symbol list
        symbols = await get_usdt_symbols(session)
        if not symbols:
            console.print("[red]No available symbols for analysis.[/red]")
            return

        while True:
            start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            tasks = [
                analyze_symbol_simple(session, symbol, args) if args.simple
                else analyze_symbol(session, symbol, args)
                for symbol in symbols
            ]

            results = []

            with Progress(
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    "[progress.percentage]{task.percentage:>3.0f}%",
                    TimeRemainingColumn(),
                    console=console
            ) as progress:
                task = progress.add_task(f"Analyzing {len(symbols)} symbols...", total=len(tasks))
                for coro in asyncio.as_completed(tasks):
                    result = await coro
                    if result:
                        results.append(result)
                    progress.advance(task)

            # Separate boosters, losers, and neutrals
            boosters = [res for res in results if res.category == "booster"]
            losers = [res for res in results if res.category == "loser"]
            neutrals = [res for res in results if res.category == "neutral"]
            # TOP N Limit for each category
            top_count = args.count

            boosters_sorted = sorted(boosters, key=lambda x: x.change_percent, reverse=True)
            # If less than N boosters, fill up from neutrals with positive change_percent
            if len(boosters_sorted) < top_count:
                positive_neutrals = [res for res in neutrals if res.change_percent > 0]
                positive_neutrals_sorted = sorted(positive_neutrals, key=lambda x: x.change_percent, reverse=True)
                needed = top_count - len(boosters_sorted)
                fillers = positive_neutrals_sorted[:needed]
                boosters_sorted.extend(fillers)
            else:
                boosters_sorted = boosters_sorted[:top_count]

            # Similarly for losers
            losers_sorted = sorted(losers, key=lambda x: x.change_percent)
            # If less than N losers, fill up from neutrals with negative change_percent
            if len(losers_sorted) < top_count:
                negative_neutrals = [res for res in neutrals if res.change_percent < 0]
                negative_neutrals_sorted = sorted(negative_neutrals, key=lambda x: x.change_percent)
                needed = top_count - len(losers_sorted)
                fillers = negative_neutrals_sorted[:needed]
                losers_sorted.extend(fillers)
            else:
                losers_sorted = losers_sorted[:top_count]

            # Ensure we have only top N in each
            boosters_sorted = boosters_sorted[:top_count]
            losers_sorted = losers_sorted[:top_count]

            # Combine results
            final_results = boosters_sorted + losers_sorted
            final_results = sorted(final_results, key=lambda x: x.change_percent, reverse=True)

            # Create table
            table = create_table_simple(final_results, start_time, args) if args.simple \
                else create_table(final_results, start_time, args)

            console.print(table)

            if not args.watch:
                break

            await asyncio.sleep(args.interval)


if __name__ == '__main__':

    # A sentinel value to check if the argument was provided by the user
    SENTINEL = object()
    sentinel_defaults = {
        'short_interval': '2d',
        'big_interval': '4d',
    }

    parser = argparse.ArgumentParser(description='Analyze price changes of USDT coins on Binance Futures.')
    parser.add_argument('current_interval', nargs='?', default='8h', help='Current interval (e.g., 1m, 5m)')
    parser.add_argument('short_interval', nargs='?', default=SENTINEL, help='Short interval (e.g., 15m, 1h)')
    parser.add_argument('big_interval', nargs='?', default=SENTINEL, help='Big interval (e.g., 4h, 1d)')
    parser.add_argument('--simple', action='store_true',    help='Simple mode, compare last price with time interval')
    parser.add_argument('--watch', action='store_true', help='Continuous monitoring mode')
    parser.add_argument('--no-spikes', action='store_true',   help="Don't show symbols if they have spike more than given threshold")
    parser.add_argument('--spike-threshold', type=str, default='5%', help='Threshold for spike detection')
    parser.add_argument('--interval', type=float, default=30.0, help='Update interval in seconds')
    parser.add_argument('--count', type=int, default=5, help='Number of symbols to display in each category')

    args = parser.parse_args()

    # Fix simple mode flag (auto enable)
    is_simple_mode = args.short_interval == SENTINEL and args.big_interval == SENTINEL
    if is_simple_mode:
        args.simple = True

    # Fix default values
    for key, value in sentinel_defaults.items():
        if getattr(args, key) is SENTINEL:
            setattr(args, key, value)

    # Set additional values
    args.spike_threshold = parse_percentage(str(args.spike_threshold))
    args.big_avg_ratio, args.short_avg_ratio = 0.5, 0.5
    args.max_concurrency = MAX_CONCURRENCY

    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        console.print("[red]Program terminated by user.[/red]")
