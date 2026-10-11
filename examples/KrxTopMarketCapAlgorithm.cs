using System;
using System.Collections.Generic;
using System.Linq;
using QuantConnect.Algorithm.Framework.Portfolio;
using QuantConnect.Data;
using QuantConnect.Data.UniverseSelection;

namespace QuantConnect.Algorithm.CSharp
{
    /// <summary>
    /// First real KRX strategy backtest (qc-krx): every month, hold the N largest KOSPI common stocks
    /// by market cap, equal weight. Uses KRX fees and taxes (KrxFeeModel), KRX tick sizes
    /// (KrxPriceVariationModel), the daily KRX universe files (KrxUniverseData) and the KOSPI 200
    /// index as benchmark (KrxIndex). Delisted stocks are part of the universe (no survivorship bias).
    ///
    /// Assumptions: common shares = codes ending in "0" (KRX convention; preferred shares end in
    /// 5/7/9/K...); selection uses the previous trading day's market cap; orders are market orders at
    /// the next daily bar; no slippage model.
    /// </summary>
    public class KrxTopMarketCapAlgorithm : QCAlgorithm
    {
        private const int Holdings = 20;
        private Dictionary<string, string> _boards;
        private int _lastSelectionMonth = -1;
        private List<Symbol> _targets = new List<Symbol>();
        private bool _rebalance;

        public override void Initialize()
        {
            SetTimeZone("Asia/Seoul");
            SetAccountCurrency("KRW");
            SetStartDate(2011, 1, 1);
            SetEndDate(2026, 9, 30);
            SetCash(1_000_000_000);

            _boards = KrxBoards.Load();
            Log($"Loaded {_boards.Count} code->market entries");
            SelfCheck();

            UniverseSettings.Resolution = Resolution.Daily;
            SetSecurityInitializer(security =>
            {
                security.SetFeeModel(new KrxFeeModel(_boards));
                security.PriceVariationModel = new KrxPriceVariationModel(_boards);
            });

            // LEAN would subscribe an index benchmark hourly; KRX index data is daily, so use a function.
            SetBenchmark(KrxIndex.Benchmark("kospi200"));

            AddUniverse<KrxUniverseData>("krx-top-market-cap", Resolution.Daily, Market.KRX, data =>
            {
                if (Time.Month == _lastSelectionMonth) return Universe.Unchanged;
                _lastSelectionMonth = Time.Month;
                _targets = data.OfType<KrxUniverseData>()
                    .Where(d => d.Board == KrxBoards.Kospi && d.Symbol.Value.EndsWith("0") && d.MarketCap > 0)
                    .OrderByDescending(d => d.MarketCap)
                    .Take(Holdings)
                    .Select(d => d.Symbol)
                    .ToList();
                _rebalance = true;
                return _targets;
            });
        }

        public override void OnData(Slice slice)
        {
            if (!_rebalance) return;
            // wait until every target has a price (new members get their first bar a day later)
            if (_targets.Any(s => !Securities.ContainsKey(s) || Securities[s].Price == 0)) return;
            _rebalance = false;
            var weight = 0.99m / _targets.Count;   // keep ~1% cash for fees and rounding
            SetHoldings(_targets.Select(s => new PortfolioTarget(s, weight)).ToList(), liquidateExistingHoldings: true);
        }

        public override void OnSecuritiesChanged(SecurityChanges changes)
        {
            foreach (var removed in changes.RemovedSecurities)
            {
                if (removed.Invested) Liquidate(removed.Symbol);
            }
        }

        public override void OnEndOfAlgorithm()
        {
            Log($"END value={Portfolio.TotalPortfolioValue:N0} KRW, fees={Portfolio.TotalFees:N0} KRW, " +
                $"holdings={Portfolio.Values.Count(h => h.Invested)}");
        }

        /// <summary>Logs model values for known cases so a run documents them.</summary>
        private void SelfCheck()
        {
            Log($"CHECK tax KOSPI 2018-06-01={KrxFeeModel.SellTaxRate(KrxBoards.Kospi, new DateTime(2018, 6, 1))} " +
                $"2019-06-03={KrxFeeModel.SellTaxRate(KrxBoards.Kospi, new DateTime(2019, 6, 3))} " +
                $"2025-01-02={KrxFeeModel.SellTaxRate(KrxBoards.Kospi, new DateTime(2025, 1, 2))} " +
                $"2026-01-02={KrxFeeModel.SellTaxRate(KrxBoards.Kospi, new DateTime(2026, 1, 2))} " +
                $"KONEX 2020={KrxFeeModel.SellTaxRate(KrxBoards.Konex, new DateTime(2020, 1, 2))} " +
                $"ETF={KrxFeeModel.SellTaxRate(KrxBoards.Etf, new DateTime(2020, 1, 2))}");
            Log($"CHECK tick 2022 KOSPI 150000={KrxPriceVariationModel.Tick(KrxBoards.Kospi, new DateTime(2022, 6, 1), 150000)} " +
                $"2023 KOSPI 150000={KrxPriceVariationModel.Tick(KrxBoards.Kospi, new DateTime(2023, 2, 1), 150000)} " +
                $"2022 KOSDAQ 150000={KrxPriceVariationModel.Tick(KrxBoards.Kosdaq, new DateTime(2022, 6, 1), 150000)} " +
                $"2023 1500={KrxPriceVariationModel.Tick(KrxBoards.Kospi, new DateTime(2023, 2, 1), 1500)} " +
                $"ETF={KrxPriceVariationModel.Tick(KrxBoards.Etf, new DateTime(2023, 2, 1), 30000)}");
        }
    }
}
