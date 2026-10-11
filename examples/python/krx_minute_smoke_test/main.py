# region imports
from AlgorithmImports import *
from krx_models import KrxBoards, krx_benchmark, krx_initialize
# endregion


class KrxMinuteSmokeTest(QCAlgorithm):
    """Smoke test for the qc-krx minute data (from Yahoo Finance), Python version of
    examples/KrxMinuteSmokeTest.cs: Samsung Electronics and KODEX 200 at minute resolution, KRX
    fees and tick sizes, buy at 09:30 and sell at 14:30 every day. Also places one off-tick limit
    order to show the tick-size rounding. Logs bars per day: Yahoo's KRX minute bars stop at 14:59.

    Minute data covers only the last few weeks: set the dates to the files under
    data/equity/krx/minute/005930/.
    """

    def initialize(self):
        self.set_time_zone("Asia/Seoul")
        self.set_account_currency("KRW")
        self.set_start_date(2026, 9, 15)
        self.set_end_date(2026, 10, 8)
        self.set_cash(100_000_000)
        boards = KrxBoards.load()
        self.set_security_initializer(lambda security: krx_initialize(security, boards))
        self.set_benchmark(krx_benchmark("kospi200"))
        # fill_forward=False so 15:00-15:29 (missing at Yahoo) stays empty instead of repeating
        # the 14:59 bar; orders after 14:59 then wait for the next day's first bar.
        self.codes = [self.add_equity(c, Resolution.MINUTE, Market.KRX, fill_forward=False).symbol
                      for c in ("005930", "069500")]
        self.days = {}
        self.limit_tested = False
        self.schedule.on(self.date_rules.every_day(self.codes[0]), self.time_rules.at(9, 30), self.buy)
        self.schedule.on(self.date_rules.every_day(self.codes[0]), self.time_rules.at(14, 30), self.liquidate)

    def buy(self):
        for symbol in self.codes:
            self.set_holdings(symbol, 0.45)
        if not self.limit_tested:
            self.limit_tested = True
            price = self.securities[self.codes[0]].price
            self.limit_order(self.codes[0], 1, price * 0.9 + 123)   # off the tick grid on purpose

    def on_data(self, slice):
        bar = slice.bars.get(self.codes[0])
        if bar is None:
            return
        day = bar.time.date()
        n, first, _ = self.days.get(day, (0, bar.time, bar.time))
        self.days[day] = (n + 1, first, bar.time)

    def on_order_event(self, e):
        if e.status == OrderStatus.SUBMITTED and self.transactions.get_order_by_id(e.order_id).type == OrderType.LIMIT:
            self.log(f"LIMIT submitted at {self.transactions.get_order_by_id(e.order_id).limit_price}")
        if e.status == OrderStatus.FILLED and self.time.day == self.start_date.day:
            self.log(f"FILL {self.time:%Y-%m-%d %H:%M} {e.symbol.value} qty={e.fill_quantity} "
                     f"price={e.fill_price} fee={e.order_fee}")

    def on_end_of_algorithm(self):
        for day, (n, first, last) in sorted(self.days.items()):
            self.log(f"DAY {day} bars={n} first={first:%H:%M} last={last:%H:%M}")
        self.log(f"END days={len(self.days)} value={self.portfolio.total_portfolio_value:,.0f} KRW "
                 f"fees={self.portfolio.total_fees:,.0f}")
