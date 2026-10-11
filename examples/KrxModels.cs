/*
 * KRX reality models and data types for QuantConnect LEAN (qc-krx).
 *
 * Copy this file into LEAN's Algorithm.CSharp project next to your algorithm. It expects the data
 * installed by `python -m qc_krx lean-install <Lean/Data>`:
 *   Data/equity/krx/securities.csv        code -> market (KOSPI / KOSDAQ / KONEX / ETF)
 *   Data/equity/krx/universe/yyyyMMdd.zip daily universe rows (code, market, close, volume,
 *                                         value, market_cap, shares)
 *
 * Tax rates and tick sizes: see docs/AUDIT.md (section "KRX reality models") for sources.
 */

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using QuantConnect.Data;
using QuantConnect.Orders;
using QuantConnect.Orders.Fees;
using QuantConnect.Securities;

namespace QuantConnect.Algorithm.CSharp
{
    /// <summary>Which KRX market each code trades on, from Data/equity/krx/securities.csv.</summary>
    public static class KrxBoards
    {
        public const string Kospi = "KOSPI", Kosdaq = "KOSDAQ", Konex = "KONEX", Etf = "ETF";

        public static Dictionary<string, string> Load(string dataFolder = null)
        {
            var path = Path.Combine(dataFolder ?? Globals.DataFolder, "equity", "krx", "securities.csv");
            var boards = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            if (!File.Exists(path)) return boards;
            var header = true;
            foreach (var line in File.ReadLines(path))
            {
                if (header) { header = false; continue; }
                var cols = SplitCsv(line);
                if (cols.Count >= 3) boards[cols[0]] = Normalize(cols[2]);
            }
            return boards;
        }

        /// <summary>KOSDAQ GLOBAL etc. count as KOSDAQ; unknown codes are treated as KOSPI.</summary>
        public static string Normalize(string market)
        {
            market = (market ?? "").Trim().ToUpperInvariant();
            if (market.StartsWith(Kosdaq)) return Kosdaq;
            if (market.StartsWith(Konex)) return Konex;
            if (market.StartsWith(Etf)) return Etf;
            return Kospi;
        }

        public static string Of(Dictionary<string, string> boards, Symbol symbol)
            => boards != null && boards.TryGetValue(symbol.Value, out var b) ? b : Kospi;

        private static List<string> SplitCsv(string line)
        {
            var cols = new List<string>();
            var cur = new System.Text.StringBuilder();
            var quoted = false;
            for (var i = 0; i < line.Length; i++)
            {
                var c = line[i];
                if (quoted)
                {
                    if (c == '"' && i + 1 < line.Length && line[i + 1] == '"') { cur.Append('"'); i++; }
                    else if (c == '"') quoted = false;
                    else cur.Append(c);
                }
                else if (c == '"') quoted = true;
                else if (c == ',') { cols.Add(cur.ToString()); cur.Clear(); }
                else cur.Append(c);
            }
            cols.Add(cur.ToString());
            return cols;
        }
    }

    /// <summary>
    /// KRX equity fees: broker commission on both sides plus, on sells, the securities transaction
    /// tax (and, on KOSPI, the 농어촌특별세 0.15%). Tax rates follow the settlement date (T+2), the
    /// basis the law uses. ETFs are exempt from the transaction tax. Amounts are truncated to won.
    /// </summary>
    public class KrxFeeModel : FeeModel
    {
        // (first settlement date, total sell-side tax rate incl. 농특세 where applicable)
        private static readonly (DateTime From, decimal Rate)[] KospiTax =
        {
            (DateTime.MinValue, 0.0030m),          // 거래세 0.15% + 농특세 0.15%
            (new DateTime(2019, 6, 3), 0.0025m),   // 0.10% + 0.15%
            (new DateTime(2021, 1, 1), 0.0023m),   // 0.08% + 0.15%
            (new DateTime(2023, 1, 1), 0.0020m),   // 0.05% + 0.15%
            (new DateTime(2024, 1, 1), 0.0018m),   // 0.03% + 0.15%
            (new DateTime(2025, 1, 1), 0.0015m),   // 0.00% + 0.15%
            (new DateTime(2026, 1, 1), 0.0020m),   // 0.05% + 0.15%
        };
        private static readonly (DateTime From, decimal Rate)[] KosdaqTax =   // no 농특세
        {
            (DateTime.MinValue, 0.0030m),
            (new DateTime(2019, 6, 3), 0.0025m),
            (new DateTime(2021, 1, 1), 0.0023m),
            (new DateTime(2023, 1, 1), 0.0020m),
            (new DateTime(2024, 1, 1), 0.0018m),
            (new DateTime(2025, 1, 1), 0.0015m),
            (new DateTime(2026, 1, 1), 0.0020m),
        };
        private static readonly (DateTime From, decimal Rate)[] KonexTax =
        {
            (DateTime.MinValue, 0.0030m),
            (new DateTime(2019, 6, 3), 0.0010m),
        };

        private readonly Dictionary<string, string> _boards;
        private readonly decimal _commissionRate;

        /// <param name="boards">code -> market, from <see cref="KrxBoards.Load"/></param>
        /// <param name="commissionRate">broker commission per side (account-specific; default 0.015%)</param>
        public KrxFeeModel(Dictionary<string, string> boards, decimal commissionRate = 0.00015m)
        {
            _boards = boards;
            _commissionRate = commissionRate;
        }

        public static decimal SellTaxRate(string board, DateTime settlementDate)
        {
            var table = board == KrxBoards.Kosdaq ? KosdaqTax : board == KrxBoards.Konex ? KonexTax
                : board == KrxBoards.Etf ? null : KospiTax;
            if (table == null) return 0m;
            var rate = 0m;
            foreach (var (from, r) in table)
            {
                if (settlementDate >= from) rate = r;
            }
            return rate;
        }

        public override OrderFee GetOrderFee(OrderFeeParameters parameters)
        {
            var security = parameters.Security;
            var order = parameters.Order;
            var value = order.AbsoluteQuantity * security.Price;
            var fee = Math.Floor(value * _commissionRate);
            if (order.Direction == OrderDirection.Sell)
            {
                var hours = security.Exchange.Hours;
                var tradeDate = order.Time.ConvertFromUtc(security.Exchange.TimeZone).Date;
                var settlement = hours.GetNextTradingDay(hours.GetNextTradingDay(tradeDate));
                fee += Math.Floor(value * SellTaxRate(KrxBoards.Of(_boards, security.Symbol), settlement));
            }
            return new OrderFee(new CashAmount(fee, "KRW"));
        }
    }

    /// <summary>
    /// KRX tick sizes (호가가격단위) by date, market and price. Unified table from 2023-01-25;
    /// before that KOSPI and KOSDAQ/KONEX tables differed above 50,000 won. ETFs: 5 won.
    /// The reference price is the price LEAN passes in (adjusted prices in Adjusted mode, so
    /// rounding is exact in Raw mode).
    /// </summary>
    public class KrxPriceVariationModel : IPriceVariationModel
    {
        private static readonly DateTime Reform2023 = new DateTime(2023, 1, 25);
        private readonly Dictionary<string, string> _boards;

        public KrxPriceVariationModel(Dictionary<string, string> boards) { _boards = boards; }

        public static decimal Tick(string board, DateTime date, decimal price)
        {
            if (board == KrxBoards.Etf) return 5m;
            if (date >= Reform2023)
            {
                return price < 2000 ? 1 : price < 5000 ? 5 : price < 20000 ? 10 : price < 50000 ? 50
                    : price < 200000 ? 100 : price < 500000 ? 500 : 1000;
            }
            if (price < 1000) return 1;
            if (price < 5000) return 5;
            if (price < 10000) return 10;
            if (price < 50000) return 50;
            if (board != KrxBoards.Kospi) return 100;    // KOSDAQ / KONEX before 2023-01-25
            return price < 100000 ? 100 : price < 500000 ? 500 : 1000;
        }

        public decimal GetMinimumPriceVariation(GetMinimumPriceVariationParameters parameters)
        {
            var security = parameters.Security;
            return Tick(KrxBoards.Of(_boards, security.Symbol), security.LocalTime.Date, parameters.ReferencePrice);
        }
    }

    /// <summary>
    /// Daily index levels from Data/index/krx/daily/{ticker}.zip. LEAN subscribes a security
    /// benchmark at hourly resolution, and the KRX data is daily only, so pass
    /// <c>SetBenchmark(KrxIndex.Benchmark("kospi200"))</c> instead of an index symbol.
    /// </summary>
    public static class KrxIndex
    {
        public static SortedList<DateTime, decimal> LoadDaily(string ticker, string dataFolder = null)
        {
            var path = Path.Combine(dataFolder ?? Globals.DataFolder, "index", "krx", "daily", $"{ticker.ToLowerInvariant()}.zip");
            var levels = new SortedList<DateTime, decimal>();
            using var zip = System.IO.Compression.ZipFile.OpenRead(path);
            using var reader = new StreamReader(zip.Entries[0].Open());
            string line;
            while ((line = reader.ReadLine()) != null)
            {
                var c = line.Split(',');
                if (c.Length < 5) continue;
                var date = DateTime.ParseExact(c[0].Substring(0, 8), "yyyyMMdd", CultureInfo.InvariantCulture);
                levels[date] = decimal.Parse(c[4], CultureInfo.InvariantCulture);
            }
            return levels;
        }

        /// <summary>Benchmark function: the last close on or before the given time.</summary>
        public static Func<DateTime, decimal> Benchmark(string ticker, string dataFolder = null)
        {
            var levels = LoadDaily(ticker, dataFolder);
            var dates = levels.Keys;
            return time =>
            {
                int lo = 0, hi = dates.Count - 1, found = -1;
                while (lo <= hi)
                {
                    var mid = (lo + hi) / 2;
                    if (dates[mid] <= time.Date) { found = mid; lo = mid + 1; } else hi = mid - 1;
                }
                return found < 0 ? levels.Values[0] : levels.Values[found];
            };
        }
    }

    /// <summary>One row of Data/equity/krx/universe/yyyyMMdd.zip: a security that traded that day.</summary>
    public class KrxUniverseData : BaseData
    {
        public string Board { get; set; }
        public decimal Close { get; set; }
        public decimal Volume { get; set; }
        public decimal TradingValue { get; set; }
        public decimal MarketCap { get; set; }
        public decimal Shares { get; set; }

        public override DateTime EndTime
        {
            get { return Time + QuantConnect.Time.OneDay; }
            set { Time = value - QuantConnect.Time.OneDay; }
        }

        public override SubscriptionDataSource GetSource(SubscriptionDataConfig config, DateTime date, bool isLiveMode)
        {
            var path = Path.Combine(Globals.DataFolder, "equity", "krx", "universe", $"{date:yyyyMMdd}.zip");
            return new SubscriptionDataSource(path, SubscriptionTransportMedium.LocalFile, FileFormat.Csv);
        }

        public override BaseData Reader(SubscriptionDataConfig config, string line, DateTime date, bool isLiveMode)
        {
            if (string.IsNullOrWhiteSpace(line) || line.StartsWith("code", StringComparison.Ordinal)) return null;
            var c = line.Split(',');
            decimal D(string s) => decimal.TryParse(s, NumberStyles.Any, CultureInfo.InvariantCulture, out var v) ? v : 0m;
            return new KrxUniverseData
            {
                Time = date,
                Symbol = Symbol.Create(c[0], SecurityType.Equity, Market.KRX),
                Board = KrxBoards.Normalize(c[1]),
                Close = D(c[2]),
                Value = D(c[2]),
                Volume = D(c[3]),
                TradingValue = D(c[4]),
                MarketCap = D(c[5]),
                Shares = D(c[6]),
            };
        }
    }
}
