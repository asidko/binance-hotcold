##################################################
# Скрипт для поиска наиболее волатильных монет на Binance
#
# Перед использованием, установить зависимости:
# pip install rich aiohttp
#
# Скриншот: https://github.com/user-attachments/assets/b22838f6-a130-4ffe-9f01-d09abbcc24cc
#
# Пример использования.
# Найти монеты которые изменились на 2% за последнюю 1 минуту в сравнении с последними 15 минутами
# python hotcold.py 2% 1m 15m
#
# Для непрерывного поиска нужно добавить параметр --watch
# python hotcold.py 2% 1m 15m --watch
#
# Возможности:
# - Анализирует пары с USDT на Binance Futures по изменению цены.
# - Показывает топ 5 монет, которые выросли, и топ 5, которые упали.
# - Режим автообновления результатов (--watch).
# - Параллельные запросы для быстрого получения данных.
##################################################

import asyncio
import aiohttp
import argparse
from typing import List, Dict, Any
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.align import Align
from rich.style import Style
from datetime import datetime

# Инициализация Rich Console
console = Console()

# Константы Binance Futures API
EXCHANGE_INFO_URL = 'https://fapi.binance.com/fapi/v1/exchangeInfo'
KLINES_URL = 'https://fapi.binance.com/fapi/v1/klines'

# Асинхронный семафор для ограничения одновременных запросов
SEMAPHORE = asyncio.Semaphore(20)  # Ограничение до 20 одновременных запросов

# Константа для количества обновлений, в течение которых отображаются монеты
DISPLAY_DURATION = 2  # Можно настроить по вашему желанию

async def fetch_json(session: aiohttp.ClientSession, url: str, params: Dict[str, Any]) -> Any:
    """
    Асинхронно выполняет GET-запрос и возвращает JSON-ответ.
    """
    try:
        async with SEMAPHORE:
            async with session.get(url, params=params, ssl=False, timeout=10) as response:
                if response.status != 200:
                    return None
                return await response.json()
    except Exception:
        return None

async def get_usdt_symbols(session: aiohttp.ClientSession) -> List[str]:
    """
    Получает список символов, торгуемых за USDT на Binance Futures.
    """
    data = await fetch_json(session, EXCHANGE_INFO_URL, {})
    if data is None:
        return []
    symbols = [s['symbol'] for s in data['symbols'] if s['quoteAsset'] == 'USDT' and s['status'] == 'TRADING']
    return symbols

def parse_percentage(pct_str: str) -> float:
    """
    Парсит строку процентного значения и возвращает его как float.
    """
    try:
        return float(pct_str.strip('%'))
    except ValueError:
        return 10.0

def parse_interval(interval_str: str) -> str:
    """
    Проверяет и возвращает корректный интервал для Binance API.
    """
    valid_intervals = [
        '1m', '3m', '5m', '15m', '30m',
        '1h', '2h', '4h', '6h', '8h',
        '12h', '1d', '3d', '1w', '1M'
    ]
    return interval_str if interval_str in valid_intervals else '1h'

def interval_to_minutes(interval: str) -> int:
    """
    Преобразует строку интервала Binance в количество минут.
    """
    mapping = {
        '1m': 1,
        '3m': 3,
        '5m': 5,
        '15m': 15,
        '30m': 30,
        '1h': 60,
        '2h': 120,
        '4h': 240,
        '6h': 360,
        '8h': 480,
        '12h': 720,
        '1d': 1440,
        '3d': 4320,
        '1w': 10080,
        '1M': 43200  # Приблизительно 30 дней
    }
    return mapping.get(interval, 0)

def get_sub_interval_and_candles(interval: str) -> (str, int):
    """
    Определяет подынтервал и количество свечей для заданного интервала.
    """
    interval_minutes = interval_to_minutes(interval)
    if interval_minutes == 0:
        return ('1m', 1)

    if interval_minutes >= 43200:  # 1 месяц или больше
        sub_interval = '1d'
    elif interval_minutes >= 10080:  # 1 неделя или больше
        sub_interval = '4h'
    elif interval_minutes >= 1440:  # 1 день или больше
        sub_interval = '1h'
    elif interval_minutes >= 60:  # 1 час или больше
        sub_interval = '5m'
    else:
        sub_interval = '1m'

    sub_interval_minutes = interval_to_minutes(sub_interval)
    num_candles = interval_minutes // sub_interval_minutes
    num_candles = max(1, num_candles)

    return (sub_interval, num_candles)

async def analyze_symbol(session: aiohttp.ClientSession, symbol: str, current_interval: str, prev_interval: str) -> Dict[str, Any]:
    """
    Анализирует изменение цены для одного символа, используя улучшенную логику.
    Возвращает одно процентное изменение, положительное или отрицательное, в зависимости от большего изменения.
    """
    try:
        # Получение свечей для текущего интервала
        current_sub_interval, current_num_candles = get_sub_interval_and_candles(current_interval)
        if current_num_candles <= 0:
            return {}

        current_klines = await fetch_json(session, KLINES_URL, {
            'symbol': symbol,
            'interval': current_sub_interval,
            'limit': current_num_candles
        })
        if not current_klines:
            return {}

        current_high_prices = [float(kline[2]) for kline in current_klines]  # High prices
        current_low_prices = [float(kline[3]) for kline in current_klines]   # Low prices
        max_current_price = max(current_high_prices)
        min_current_price = min(current_low_prices)

        # Определение подынтервала и количества свечей для предыдущего интервала
        prev_sub_interval, prev_num_candles = get_sub_interval_and_candles(prev_interval)
        if prev_num_candles <= 0:
            return {}

        # Запрос свечей за предыдущий интервал
        prev_klines = await fetch_json(session, KLINES_URL, {
            'symbol': symbol,
            'interval': prev_sub_interval,
            'limit': prev_num_candles
        })
        if not prev_klines:
            return {}

        prev_high_prices = [float(kline[2]) for kline in prev_klines]  # High prices
        prev_low_prices = [float(kline[3]) for kline in prev_klines]   # Low prices
        max_prev_price = max(prev_high_prices)
        min_prev_price = min(prev_low_prices)
        avg_prev_price = sum(prev_high_prices) / len(prev_high_prices)
        biased_prev_price = avg_prev_price + (max_prev_price - avg_prev_price) * 0.5  # Смещенное среднее

        # Вычисление процентного изменения для роста и падения
        pct_change_up = ((max_current_price - biased_prev_price) / biased_prev_price) * 100
        pct_change_down = ((min_current_price - biased_prev_price) / biased_prev_price) * 100

        # Выбор изменения с наибольшей абсолютной величиной
        if abs(pct_change_up) >= abs(pct_change_down):
            change = pct_change_up
        else:
            change = pct_change_down

        return {
            'symbol': symbol,
            'change': change,
            'current_price': max_current_price if change >= 0 else min_current_price,
            'prev_price': biased_prev_price
        }
    except Exception:
        return {}

def create_table(sorted_symbols: List[Dict[str, Any]], top_rising_symbols: List[str], top_falling_symbols: List[str], change_threshold: float, last_updated: str) -> Table:
    """
    Создает таблицу с результатами, отсортированную по процентному изменению.
    """
    table = Table(title=f"Волатильные монеты USDT (Обновлено: {last_updated})")
    table.add_column("Символ", style="cyan", no_wrap=True)
    table.add_column("Изменение (%)", style="magenta")
    table.add_column("Текущая цена", style="green")
    table.add_column("Предыдущая цена", style="green")

    for res in sorted_symbols:
        symbol = res['symbol']
        change = res['change']
        current_price = res['current_price']
        prev_price = res['prev_price']

        if symbol in top_rising_symbols and change >= change_threshold:
            symbol_display = f"🔥 {symbol}"
            change_display = f"[green]{change:.2f}[/green]"
        elif symbol in top_falling_symbols and change <= -change_threshold:
            symbol_display = f"❄️ {symbol}"
            change_display = f"[red]{change:.2f}[/red]"
        else:
            symbol_display = symbol
            change_display = f"[grey70]{change:.2f}[/grey70]"

        table.add_row(
            symbol_display,
            change_display,
            f"{current_price}",
            f"{prev_price:.4f}"
        )

    return table

async def main(change_threshold: float, current_interval: str, prev_interval: str, watch: bool, watch_interval: float):
    """
    Главная асинхронная функция.
    """
    console.print("Получение списка символов...")
    async with aiohttp.ClientSession() as session:
        symbols = await get_usdt_symbols(session)
        if not symbols:
            console.print("Нет доступных символов для анализа.")
            return

        console.print(f"Найдено {len(symbols)} символов с USDT.")
        console.print("Начинаем анализ...")

        tracked_symbols = {}  # Словарь для отслеживания символов и оставшихся обновлений

        with Live(console=console, refresh_per_second=1) as live:
            while True:
                start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                tasks = [analyze_symbol(session, symbol, current_interval, prev_interval) for symbol in symbols]
                results = await asyncio.gather(*tasks)
                results = [res for res in results if res]

                if results:
                    # Отделяем результаты на рост и падение
                    rising_results = [res for res in results if res['change'] >= change_threshold]
                    falling_results = [res for res in results if res['change'] <= -change_threshold]

                    # Сортировка по процентному изменению
                    top_rising = sorted(rising_results, key=lambda x: x['change'], reverse=True)[:5]
                    top_falling = sorted(falling_results, key=lambda x: x['change'])[:5]

                    # Определяем символы, вошедшие в топ-растущие и топ-падающие
                    top_rising_symbols = [res['symbol'] for res in top_rising]
                    top_falling_symbols = [res['symbol'] for res in top_falling]

                    # Если недостаточно символов, добавляем остальные
                    total_needed = 10
                    current_total = len(top_rising) + len(top_falling)
                    if current_total < total_needed:
                        remaining = [res for res in results if res['symbol'] not in top_rising_symbols and res['symbol'] not in top_falling_symbols]
                        # Сортируем по абсолютному изменению
                        remaining_sorted = sorted(remaining, key=lambda x: abs(x['change']), reverse=True)
                        needed = total_needed - current_total
                        other_symbols = remaining_sorted[:needed]
                    else:
                        other_symbols = []

                    # Объединяем все символы
                    final_symbols = top_rising + top_falling + other_symbols

                    # Сортируем итоговый список по процентному изменению
                    sorted_final_symbols = sorted(final_symbols, key=lambda x: x['change'], reverse=True)

                    # Обновляем счетчик для отслеживаемых символов
                    new_tracked_symbols = {}
                    for res in final_symbols:
                        symbol = res['symbol']
                        if abs(res['change']) >= change_threshold:
                            new_tracked_symbols[symbol] = DISPLAY_DURATION
                    # Уменьшаем счетчик для ранее отслеживаемых символов
                    for symbol in tracked_symbols:
                        if symbol not in new_tracked_symbols:
                            if tracked_symbols[symbol] > 1:
                                new_tracked_symbols[symbol] = tracked_symbols[symbol] - 1
                    tracked_symbols = new_tracked_symbols

                    # Создание таблицы
                    table = create_table(sorted_final_symbols, top_rising_symbols, top_falling_symbols, change_threshold, start_time)
                else:
                    table = Table(title=f"Волатильные монеты USDT (Обновлено: {start_time})")
                    table.add_column("Символ", style="cyan", no_wrap=True)
                    table.add_column("Изменение (%)", style="magenta")
                    table.add_column("Текущая цена", style="green")
                    table.add_column("Предыдущая цена", style="green")
                    table.add_row("-", "-", "-", "-")

                live.update(Align.center(table))

                if not watch:
                    break

                await asyncio.sleep(watch_interval)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Анализ изменений цен монет USDT на Binance Futures.')
    parser.add_argument('percentage', nargs='?', default='10%', help='Порог изменения цены (например, 10%)')
    parser.add_argument('current_interval', nargs='?', default='1m', help='Текущий интервал (например, 1m, 15m, 1h)')
    parser.add_argument('prev_interval', nargs='?', default='15m', help='Предыдущий интервал для сравнения (например, 15m, 1h)')
    parser.add_argument('--watch', action='store_true', help='Режим постоянного мониторинга')
    parser.add_argument('--interval', type=float, default=5.0, help='Интервал обновления в секундах (по умолчанию 5 секунд)')

    args = parser.parse_args()

    change_threshold = parse_percentage(args.percentage)
    current_interval = parse_interval(args.current_interval)
    prev_interval = parse_interval(args.prev_interval)
    watch = args.watch
    watch_interval = args.interval

    try:
        asyncio.run(main(change_threshold, current_interval, prev_interval, watch, watch_interval))
    except KeyboardInterrupt:
        console.print("Программа завершена пользователем.")
