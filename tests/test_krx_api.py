import datetime as dt
import tempfile
import unittest
from pathlib import Path

from qc_krx import build, krx_api

# Trimmed from KRX's sample endpoint responses (svc/sample/apis/...).
KOSDAQ_ROWS = [
    {"BAS_DD": "20200414", "ISU_CD": "900100", "ISU_NM": "뉴프라이드", "MKT_NM": "KOSDAQ",
     "SECT_TP_NM": "외국기업(소속부없음)", "TDD_CLSPRC": "717", "CMPPREVDD_PRC": "0", "FLUC_RT": "0.00",
     "TDD_OPNPRC": "0", "TDD_HGPRC": "0", "TDD_LWPRC": "0", "ACC_TRDVOL": "0", "ACC_TRDVAL": "0",
     "MKTCAP": "74162628276", "LIST_SHRS": "103434628"},
    {"BAS_DD": "20200414", "ISU_CD": "005930", "ISU_NM": "삼성전자", "MKT_NM": "KOSDAQ",
     "SECT_TP_NM": "", "TDD_CLSPRC": "49000", "CMPPREVDD_PRC": "0", "FLUC_RT": "0.00",
     "TDD_OPNPRC": "48500", "TDD_HGPRC": "49500", "TDD_LWPRC": "48000", "ACC_TRDVOL": "100", "ACC_TRDVAL": "1",
     "MKTCAP": "1", "LIST_SHRS": "1"},
]
# ETF rows on a holiday carry empty prices.
ETF_HOLIDAY_ROW = {"BAS_DD": "20261005", "ISU_CD": "0184E0", "ISU_NM": "1Q 200채권혼합50액티브",
                   "TDD_CLSPRC": "", "TDD_OPNPRC": "", "TDD_HGPRC": "", "TDD_LWPRC": "", "ACC_TRDVOL": ""}


class FakeClient:
    def __init__(self, data):
        self.data = data  # (market, date) -> rows
        self.calls = []

    def get_day(self, market, date, endpoints=krx_api.ENDPOINTS):
        self.calls.append((market, date))
        return self.data.get((market, date), [])


class KrxApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_day_file_roundtrip(self):
        path = krx_api.day_path(self.root, "KOSDAQ", "20200414")
        krx_api.write_day(path, KOSDAQ_ROWS)
        self.assertEqual(krx_api.read_day(path), KOSDAQ_ROWS)
        empty = krx_api.day_path(self.root, "KOSDAQ", "20200415")
        krx_api.write_day(empty, [])
        self.assertEqual(krx_api.read_day(empty), [])

    def test_scrape_skips_weekends_resumes_and_caches_old_empty_days(self):
        client = FakeClient({("KOSDAQ", "20200414"): KOSDAQ_ROWS})
        # 2020-04-10 is a Friday; 11-12 are the weekend; 13 has no data (empty, old -> cached).
        stats = krx_api.scrape_krx(client, self.root, start="20200410", end="20200414", markets=["KOSDAQ"])
        self.assertEqual(client.calls, [("KOSDAQ", d) for d in ("20200410", "20200413", "20200414")])
        self.assertEqual(stats["rows"], 2)
        self.assertTrue(krx_api.day_path(self.root, "KOSDAQ", "20200413").exists())

        client.calls.clear()
        krx_api.scrape_krx(client, self.root, start="20200410", end="20200414", markets=["KOSDAQ"])
        self.assertEqual(client.calls, [])

    def test_recent_empty_day_is_not_cached(self):
        today = dt.datetime.now(krx_api.KST).date()
        d = today - dt.timedelta(days=(today.weekday() - 4) % 7 or 7)  # a recent weekday in the past
        date = d.strftime("%Y%m%d")
        krx_api.scrape_krx(FakeClient({}), self.root, start=date, end=date, markets=["KOSPI"])
        self.assertFalse(krx_api.day_path(self.root, "KOSPI", date).exists())

    def test_konex_start_is_clamped(self):
        client = FakeClient({})
        krx_api.scrape_krx(client, self.root, start="20130627", end="20130702", markets=["KONEX"])
        self.assertEqual([d for _, d in client.calls], ["20130701", "20130702"])

    def test_build_prefers_krx_and_records_securities(self):
        krx_api.write_day(krx_api.day_path(self.root, "KOSDAQ", "20200414"), KOSDAQ_ROWS)
        krx_api.write_day(krx_api.day_path(self.root, "ETF", "20261005"), [ETF_HOLIDAY_ROW])
        hist = self.root / "raw" / "history"
        hist.mkdir(parents=True)
        (hist / "005930.csv").write_text("date,close,volume\n20200413,48000,7\n20200414,1,1\n", encoding="utf-8")

        self.assertEqual(build.build(self.root), 2)
        rows = (self.root / "ohlcv" / "005930.csv").read_text(encoding="utf-8").splitlines()
        self.assertEqual(rows[1:], ["20200413,48000,48000,48000,48000,7,history",
                                    "20200414,48500,49500,48000,49000,100,krx"])
        # No-trade day: open/high/low of 0 fall back to the close.
        self.assertIn("20200414,717,717,717,717,0,krx",
                      (self.root / "ohlcv" / "900100.csv").read_text(encoding="utf-8"))
        # The ETF holiday row has no price, so nothing is written for it.
        self.assertFalse((self.root / "ohlcv" / "0184E0.csv").exists())
        sec = (self.root / "securities.csv").read_text(encoding="utf-8")
        self.assertIn("900100,뉴프라이드,KOSDAQ,20200414,20200414", sec)
        self.assertFalse((self.root / ".build").exists())

    def test_indices_and_security_info(self):
        index_rows = [
            {"BAS_DD": "20261006", "IDX_CLSS": "KOSPI", "IDX_NM": "코스피 (외국주포함)", "CLSPRC_IDX": "",
             "OPNPRC_IDX": "", "HGPRC_IDX": "", "LWPRC_IDX": "", "ACC_TRDVOL": "1", "ACC_TRDVAL": "1", "MKTCAP": "1"},
            {"BAS_DD": "20261006", "IDX_CLSS": "KOSPI", "IDX_NM": "코스피", "CLSPRC_IDX": "6941.39",
             "OPNPRC_IDX": "7044.67", "HGPRC_IDX": "7044.67", "LWPRC_IDX": "6897.38",
             "ACC_TRDVOL": "269406569", "ACC_TRDVAL": "20077224633617", "MKTCAP": "5722775392085816"},
            {"BAS_DD": "20261006", "IDX_CLSS": "KOSPI", "IDX_NM": "코스피 200 철강/소재", "CLSPRC_IDX": "1000.5",
             "OPNPRC_IDX": "-", "HGPRC_IDX": "-", "LWPRC_IDX": "-", "ACC_TRDVOL": "0", "ACC_TRDVAL": "0", "MKTCAP": "0"},
        ]
        client = FakeClient({("KOSPI", "20261006"): index_rows})
        krx_api.scrape_krx(client, self.root, start="20261006", end="20261006", markets=["KOSPI"], dataset="index")
        self.assertTrue(krx_api.day_path(self.root, "KOSPI", "20261006", "krx_index").exists())

        krx_api.write_day(krx_api.info_path(self.root, "KOSDAQ", "20200414"), [{
            "ISU_CD": "KR7900100000", "ISU_SRT_CD": "900100", "ISU_NM": "x", "ISU_ABBRV": "x", "ISU_ENG_NM": "New Pride",
            "LIST_DD": "20100101", "MKT_TP_NM": "KOSDAQ", "SECUGRP_NM": "외국주권", "SECT_TP_NM": "",
            "KIND_STKCERT_TP_NM": "보통주", "PARVAL": "500", "LIST_SHRS": "1"}])
        krx_api.write_day(krx_api.day_path(self.root, "KOSDAQ", "20200414"), KOSDAQ_ROWS)
        build.build(self.root)

        self.assertEqual((self.root / "index" / "KOSPI.csv").read_text(encoding="utf-8").splitlines()[1],
                         "20261006,7044.67,7044.67,6897.38,6941.39,269406569,20077224633617,5722775392085816")
        self.assertIn("20261006,1000.5,1000.5,1000.5,1000.5,",
                      (self.root / "index" / "KOSPI_코스피_200_철강_소재.csv").read_text(encoding="utf-8"))
        catalog = (self.root / "indices.csv").read_text(encoding="utf-8")
        self.assertNotIn("외국주포함", catalog)  # no levels reported -> no file
        sec = (self.root / "securities.csv").read_text(encoding="utf-8").splitlines()
        self.assertTrue(sec[0].endswith("isin,name_en,listing_date,security_group,share_class,par_value"))
        self.assertIn("900100,뉴프라이드,KOSDAQ,20200414,20200414,KR7900100000,New Pride,20100101,외국주권,보통주,500", sec)


if __name__ == "__main__":
    unittest.main()
