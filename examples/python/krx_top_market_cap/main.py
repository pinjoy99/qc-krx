# region imports
from AlgorithmImports import *
from krx_models import (KOSPI, ETF, KONEX, KOSDAQ, KrxBoards, KrxUniverseData, krx_benchmark,
                        krx_initialize, sell_tax_rate, tick_size)
# endregion


class KrxTopMarketCapAlgorithm(QCAlgorithm):
    """qc-krx example strategy, Python version of examples/KrxTopMarketCapAlgorithm.cs: every month,
    hold the N largest KOSPI common stocks by market cap, equal weight, with KRX fees and taxes,
    KRX tick sizes, the daily KRX universe files and the KOSPI 200 index as benchmark.
    Delisted stocks are part of the universe (no survivorship bias).

    Assumptions: common shares = codes ending in "0" (KRX convention); selection uses the previous
    trading day's market cap; market orders at the next daily bar; no slippage model.
    """

    HOLDINGS = 20   # default; parameter "holdings" overrides it (klean backtest/optimize --parameter holdings N)

    def initialize(self):
        self.set_time_zone("Asia/Seoul")
        self.set_account_currency("KRW")
        self.set_start_date(2011, 1, 1)
        self.set_end_date(2026, 9, 30)
        self.set_cash(1_000_000_000)

        self.holdings = int(self.get_parameter("holdings", str(self.HOLDINGS)))
        self.boards = KrxBoards.load()
        self.log(f"Loaded {len(self.boards)} code->market entries")
        self.self_check()

        self.universe_settings.resolution = Resolution.DAILY
        self.set_security_initializer(lambda security: krx_initialize(security, self.boards))
        self.set_benchmark(krx_benchmark("kospi200"))

        self.last_month = -1
        self.targets = []
        self.rebalance = False
        self.add_universe(KrxUniverseData, SecurityType.EQUITY, "krx-top-market-cap", Resolution.DAILY,
                          Market.KRX, self.select)

    def select(self, data):
        if self.time.month == self.last_month:
            return Universe.UNCHANGED
        self.last_month = self.time.month
        rows = [d for d in data
                if d["board"] == KOSPI and d.symbol.value.endswith("0") and d["market_cap"] > 0]
        rows.sort(key=lambda d: d["market_cap"], reverse=True)
        self.targets = [d.symbol for d in rows[:self.holdings]]
        self.rebalance = True
        return self.targets

    def on_data(self, slice):
        if not self.rebalance:
            return
        # wait until every target has a price (new members get their first bar a day later)
        if any(s not in self.securities or self.securities[s].price == 0 for s in self.targets):
            return
        self.rebalance = False
        weight = 0.99 / len(self.targets)   # keep ~1% cash for fees and rounding
        self.set_holdings([PortfolioTarget(s, weight) for s in self.targets], liquidate_existing_holdings=True)

    def on_securities_changed(self, changes):
        for removed in changes.removed_securities:
            if removed.invested:
                self.liquidate(removed.symbol)

    def on_end_of_algorithm(self):
        held = sum(1 for h in self.portfolio.values() if h.invested)
        self.log(f"END value={self.portfolio.total_portfolio_value:,.0f} KRW, "
                 f"fees={self.portfolio.total_fees:,.0f} KRW, holdings={held}")

    def self_check(self):
        """Logs model values for known cases so a run documents them."""
        d = date
        self.log(f"CHECK tax KOSPI 2018-06-01={sell_tax_rate(KOSPI, d(2018, 6, 1))} "
                 f"2019-06-03={sell_tax_rate(KOSPI, d(2019, 6, 3))} 2025-01-02={sell_tax_rate(KOSPI, d(2025, 1, 2))} "
                 f"2026-01-02={sell_tax_rate(KOSPI, d(2026, 1, 2))} KONEX 2020={sell_tax_rate(KONEX, d(2020, 1, 2))} "
                 f"ETF={sell_tax_rate(ETF, d(2020, 1, 2))}")
        self.log(f"CHECK tick 2022 KOSPI 150000={tick_size(KOSPI, d(2022, 6, 1), 150000)} "
                 f"2023 KOSPI 150000={tick_size(KOSPI, d(2023, 2, 1), 150000)} "
                 f"2022 KOSDAQ 150000={tick_size(KOSDAQ, d(2022, 6, 1), 150000)} "
                 f"2023 1500={tick_size(KOSPI, d(2023, 2, 1), 1500)} ETF={tick_size(ETF, d(2023, 2, 1), 30000)}")
