"""KRX reality models and data types for QuantConnect LEAN, in Python (qc-krx).

Copy this file next to your algorithm's main.py (in a `lean init` workspace: into the project
folder). It reads the data installed by `python -m qc_krx lean-install <workspace>/data`:

    data/equity/krx/securities.csv          code -> market (KOSPI / KOSDAQ / KONEX / ETF)
    data/equity/krx/universe/yyyyMMdd.zip   daily universe rows (code, market, close, volume,
                                            value, market_cap, shares)
    data/index/krx/daily/{index}.zip        daily index levels (kospi, kospi200)

Same rules as examples/KrxModels.cs (the C# version); tax rates and tick sizes and their sources
are in docs/AUDIT.md, section "KRX reality models".

    from krx_models import KrxBoards, KrxFeeModel, KrxPriceVariationModel, KrxUniverseData, krx_benchmark

    boards = KrxBoards.load()
    self.set_security_initializer(lambda s: krx_initialize(s, boards))
    self.set_benchmark(krx_benchmark("kospi200"))
"""

from AlgorithmImports import *

import bisect
import csv
import os
import zipfile
from datetime import date, datetime, timedelta
from decimal import ROUND_FLOOR, Decimal

KOSPI, KOSDAQ, KONEX, ETF = "KOSPI", "KOSDAQ", "KONEX", "ETF"


def _data_folder() -> str:
    return str(Globals.data_folder)


class KrxBoards:
    """Which KRX market each code trades on, from data/equity/krx/securities.csv."""

    @staticmethod
    def load(data_folder: str = None) -> dict:
        path = os.path.join(data_folder or _data_folder(), "equity", "krx", "securities.csv")
        boards = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    boards[row["code"].upper()] = KrxBoards.normalize(row["market"])
        return boards

    @staticmethod
    def normalize(market: str) -> str:
        """KOSDAQ GLOBAL etc. count as KOSDAQ; unknown markets are treated as KOSPI."""
        market = (market or "").strip().upper()
        for board in (KOSDAQ, KONEX, ETF):
            if market.startswith(board):
                return board
        return KOSPI

    @staticmethod
    def of(boards: dict, symbol) -> str:
        return boards.get(str(symbol.value).upper(), KOSPI) if boards else KOSPI


# (first settlement date, total sell-side tax rate incl. 농어촌특별세 where applicable)
_KOSPI_TAX = [(date.min, 0.0030),          # 거래세 0.15% + 농특세 0.15%
              (date(2019, 6, 3), 0.0025),  # 0.10% + 0.15%
              (date(2021, 1, 1), 0.0023),  # 0.08% + 0.15%
              (date(2023, 1, 1), 0.0020),  # 0.05% + 0.15%
              (date(2024, 1, 1), 0.0018),  # 0.03% + 0.15%
              (date(2025, 1, 1), 0.0015),  # 0.00% + 0.15%
              (date(2026, 1, 1), 0.0020)]  # 0.05% + 0.15%
_KOSDAQ_TAX = list(_KOSPI_TAX)             # same totals, no 농특세
_KONEX_TAX = [(date.min, 0.0030), (date(2019, 6, 3), 0.0010)]


def sell_tax_rate(board: str, settlement_date: date) -> float:
    """Sell-side tax rate by market and settlement date (T+2, the basis the law uses). ETFs: 0."""
    table = {KOSDAQ: _KOSDAQ_TAX, KONEX: _KONEX_TAX, ETF: None}.get(board, _KOSPI_TAX)
    rate = 0.0
    for start, r in table or []:
        if settlement_date >= start:
            rate = r
    return rate


def _floor(x: Decimal) -> Decimal:
    return x.to_integral_value(rounding=ROUND_FLOOR)


class KrxFeeModel(FeeModel):
    """Broker commission on both sides plus, on sells, the securities transaction tax (and, on
    KOSPI, the 농어촌특별세). Tax follows the settlement date (T+2). Amounts are truncated to won."""

    def __init__(self, boards: dict, commission_rate: float = 0.00015):
        super().__init__()
        self.boards = boards
        self.commission_rate = commission_rate   # per side; account-specific (default 0.015%)

    def get_order_fee(self, parameters: OrderFeeParameters) -> OrderFee:
        security, order = parameters.security, parameters.order
        # Decimal arithmetic like the C# model, so truncating to whole won gives identical fees.
        value = Decimal(str(order.absolute_quantity)) * Decimal(str(security.price))
        fee = _floor(value * Decimal(str(self.commission_rate)))
        if order.direction == OrderDirection.SELL:
            hours = security.exchange.hours
            trade_date = Extensions.convert_from_utc(order.time, security.exchange.time_zone).date()
            trade_day = datetime(trade_date.year, trade_date.month, trade_date.day)
            settlement = hours.get_next_trading_day(hours.get_next_trading_day(trade_day))
            rate = sell_tax_rate(KrxBoards.of(self.boards, security.symbol), settlement.date())
            fee += _floor(value * Decimal(str(rate)))
        return OrderFee(CashAmount(float(fee), "KRW"))


_REFORM_2023 = date(2023, 1, 25)


def tick_size(board: str, day: date, price: float) -> int:
    """KRX tick size (호가가격단위) by market, date and price. Unified table from 2023-01-25; before
    that KOSPI and KOSDAQ/KONEX differed above 50,000 won. ETFs: 5 won."""
    if board == ETF:
        return 5
    if day >= _REFORM_2023:
        for limit, tick in ((2000, 1), (5000, 5), (20000, 10), (50000, 50), (200000, 100), (500000, 500)):
            if price < limit:
                return tick
        return 1000
    for limit, tick in ((1000, 1), (5000, 5), (10000, 10), (50000, 50)):
        if price < limit:
            return tick
    if board != KOSPI:   # KOSDAQ / KONEX before 2023-01-25
        return 100
    return 100 if price < 100000 else 500 if price < 500000 else 1000


class KrxPriceVariationModel(SecurityPriceVariationModel):
    """KRX tick sizes for LEAN: limit/stop prices are rounded to them. The reference price is the
    price LEAN passes in (adjusted prices in Adjusted mode, so rounding is exact in Raw mode)."""

    __namespace__ = "QcKrx"   # lets pythonnet build a .NET subclass whose override LEAN calls

    def __init__(self, boards: dict):
        super().__init__()
        self.boards = boards

    def get_minimum_price_variation(self, parameters: GetMinimumPriceVariationParameters) -> float:
        security = parameters.security
        return tick_size(KrxBoards.of(self.boards, security.symbol), security.local_time.date(),
                         float(parameters.reference_price))

    GetMinimumPriceVariation = get_minimum_price_variation   # the .NET name LEAN calls


def krx_initialize(security, boards: dict, commission_rate: float = 0.00015) -> None:
    """Security initializer: KRX fees/taxes and tick sizes. Use with
    ``self.set_security_initializer(lambda s: krx_initialize(s, boards))``."""
    security.set_fee_model(KrxFeeModel(boards, commission_rate))
    security.price_variation_model = KrxPriceVariationModel(boards)


def load_index(ticker: str, data_folder: str = None) -> tuple:
    """(dates, closes) from data/index/krx/daily/{ticker}.zip."""
    path = os.path.join(data_folder or _data_folder(), "index", "krx", "daily", f"{ticker.lower()}.zip")
    dates, closes = [], []
    with zipfile.ZipFile(path) as z:
        for line in z.read(z.namelist()[0]).decode().splitlines():
            c = line.split(",")
            if len(c) >= 5:
                dates.append(datetime.strptime(c[0][:8], "%Y%m%d").date())
                closes.append(float(c[4]))
    return dates, closes


def krx_benchmark(ticker: str = "kospi200", data_folder: str = None):
    """Benchmark function for ``self.set_benchmark(...)``: the last daily close on or before the
    time asked. (LEAN would subscribe an index symbol hourly, but the KRX index data is daily.)"""
    dates, closes = load_index(ticker, data_folder)

    def level(time) -> float:
        i = bisect.bisect_right(dates, time.date()) - 1
        return closes[max(i, 0)]
    return level


class KrxUniverseData(PythonData):
    """One row of data/equity/krx/universe/yyyyMMdd.zip: a security that traded that day.
    Properties: board, close, volume, trading_value, market_cap, shares (raw KRW)."""

    def get_source(self, config, date, is_live):
        path = os.path.join(_data_folder(), "equity", "krx", "universe", f"{date:%Y%m%d}.zip")
        return SubscriptionDataSource(path, SubscriptionTransportMedium.LOCAL_FILE, FileFormat.CSV)

    def reader(self, config, line, date, is_live):
        if not line or line.startswith("code"):
            return None
        c = line.split(",")

        def num(s):
            try:
                return float(s)
            except ValueError:
                return 0.0
        row = KrxUniverseData()
        row.symbol = Symbol.create(c[0], SecurityType.EQUITY, Market.KRX)
        row.time = date
        row.end_time = date + timedelta(days=1)
        row.value = num(c[2])
        row["board"] = KrxBoards.normalize(c[1])
        row["close"] = num(c[2])
        row["volume"] = num(c[3])
        row["trading_value"] = num(c[4])
        row["market_cap"] = num(c[5])
        row["shares"] = num(c[6])
        return row
