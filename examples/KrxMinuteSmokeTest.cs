using System;
using System.Collections.Generic;
using System.Linq;
using QuantConnect.Data;

namespace QuantConnect.Algorithm.CSharp
{
    /// <summary>
    /// Smoke test for the qc-krx minute data (from Yahoo Finance): Samsung Electronics and the
    /// KODEX 200 ETF at minute resolution, KRX fee and tick models, a buy at 09:30 and a sale at
    /// 14:30 each day. Logs the bars per day and the first/last bar time, because Yahoo's KRX
    /// minute bars stop at 14:59 (no 15:00-15:30, no closing auction).
    ///
    /// Minute data covers only the last few weeks (see docs/AUDIT.md); set the dates to match
    /// the files under Data/equity/krx/minute.
    /// </summary>
    public class KrxMinuteSmokeTest : QCAlgorithm
    {
        private Dictionary<string, string> _boards;
        private readonly List<Symbol> _symbols = new();
        private readonly Dictionary<DateTime, (int Bars, DateTime First, DateTime Last)> _days = new();

        public override void Initialize()
        {
            SetTimeZone("Asia/Seoul");
            SetAccountCurrency("KRW");
            SetStartDate(2026, 9, 15);
            SetEndDate(2026, 10, 8);
            SetCash(100_000_000);
            _boards = KrxBoards.Load();
            SetSecurityInitializer(security =>
            {
                security.SetFeeModel(new KrxFeeModel(_boards));
                security.PriceVariationModel = new KrxPriceVariationModel(_boards);
            });
            SetBenchmark(KrxIndex.Benchmark("kospi200"));
            // fillForward: false so 15:00-15:29 (missing at Yahoo) stays empty instead of
            // repeating the 14:59 bar; orders after 14:59 then wait for the next day's first bar.
            foreach (var code in new[] { "005930", "069500" })
                _symbols.Add(AddEquity(code, Resolution.Minute, Market.KRX, fillForward: false).Symbol);

            Schedule.On(DateRules.EveryDay(_symbols[0]), TimeRules.At(9, 30), () =>
            {
                foreach (var s in _symbols) SetHoldings(s, 0.45m);
            });
            Schedule.On(DateRules.EveryDay(_symbols[0]), TimeRules.At(14, 30), () => Liquidate());
        }

        public override void OnData(Slice slice)
        {
            if (!slice.Bars.TryGetValue(_symbols[0], out var bar)) return;
            var day = bar.Time.Date;
            _days[day] = _days.TryGetValue(day, out var d)
                ? (d.Bars + 1, d.First, bar.Time)
                : (1, bar.Time, bar.Time);
        }

        public override void OnOrderEvent(Orders.OrderEvent e)
        {
            if (e.Status == Orders.OrderStatus.Filled && Time.Day == StartDate.Day)
                Log($"FILL {Time:yyyy-MM-dd HH:mm} {e.Symbol.Value} qty={e.FillQuantity} price={e.FillPrice} fee={e.OrderFee}");
        }

        public override void OnEndOfAlgorithm()
        {
            foreach (var kv in _days)
                Log($"DAY {kv.Key:yyyy-MM-dd} bars={kv.Value.Bars} first={kv.Value.First:HH:mm} last={kv.Value.Last:HH:mm}");
            Log($"END days={_days.Count} value={Portfolio.TotalPortfolioValue:N0} KRW " +
                $"fees={Portfolio.TotalFees:N0} trades={Transactions.GetOrders().Count()}");
        }
    }
}
