using System.Linq;
using QuantConnect.Data;
using QuantConnect.Data.Market;

namespace QuantConnect.Algorithm.CSharp
{
    /// <summary>
    /// Smoke test for qc-krx data: KRX equities in KRW, adjusted prices from factor files,
    /// split/dividend events, and a delisting from a map file.
    /// </summary>
    public class KrxSmokeTest : QCAlgorithm
    {
        private Symbol _samsung;
        private Symbol _woori;

        public override void Initialize()
        {
            SetTimeZone("Asia/Seoul");
            SetAccountCurrency("KRW");
            SetStartDate(2018, 4, 20);
            SetEndDate(2019, 3, 1);
            SetCash(100_000_000);
            // LEAN's default (Interactive Brokers) fee model has no KRX equity schedule; a real
            // KRX fee model (commission + sell-side transaction tax) belongs in the algorithm.
            SetSecurityInitializer(security => security.SetFeeModel(new QuantConnect.Orders.Fees.ConstantFeeModel(0, "KRW")));
            _samsung = AddEquity("005930", Resolution.Daily, Market.KRX).Symbol;
            _woori = AddEquity("000030", Resolution.Daily, Market.KRX).Symbol;
            SetBenchmark(_samsung);

        }

        public override void OnData(Slice slice)
        {
            foreach (var kv in slice.Splits) Log($"SPLIT {Time:yyyy-MM-dd} {kv.Key.Value} factor={kv.Value.SplitFactor} type={kv.Value.Type}");
            foreach (var kv in slice.Dividends) Log($"DIVIDEND {Time:yyyy-MM-dd} {kv.Key.Value} amount={kv.Value.Distribution}");
            foreach (var kv in slice.Delistings) Log($"DELISTING {Time:yyyy-MM-dd} {kv.Key.Value} type={kv.Value.Type}");
            if (slice.Bars.TryGetValue(_samsung, out var bar) && Time.Year == 2018 && Time.Month == 5 && Time.Day <= 9)
                Log($"ADJ {Time:yyyy-MM-dd} close={bar.Close}");
            if (!Portfolio.Invested && slice.Bars.ContainsKey(_samsung) && slice.Bars.ContainsKey(_woori))
            {
                SetHoldings(_samsung, 0.5m);
                SetHoldings(_woori, 0.3m);
            }
        }

        public override void OnEndOfAlgorithm()
        {
            var raw = History(_samsung, new System.DateTime(2018, 4, 27), new System.DateTime(2018, 5, 10),
                Resolution.Daily, dataNormalizationMode: DataNormalizationMode.Raw);
            foreach (var bar in raw) Log($"RAW {bar.EndTime:yyyy-MM-dd} close={bar.Close}");
            Log($"END value={Portfolio.TotalPortfolioValue:N0} KRW holdings: " +
                string.Join(", ", Portfolio.Values.Where(h => h.Invested).Select(h => $"{h.Symbol.Value}={h.Quantity}")));
        }
    }
}
