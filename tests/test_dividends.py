import tempfile
import unittest
from pathlib import Path
from unittest import mock

from qc_krx import dividends
from qc_krx.krx_api import write_day


def row(**kw):
    base = {"basDt": "20261009", "crno": "1", "isinCd": "KR7005930003", "stckIssuCmpyNm": "삼성전자",
            "isinCdNm": "삼성전자", "scrsItmsKcd": "0101", "scrsItmsKcdNm": "보통주", "stckParPrc": "100",
            "trsnmDptyDcd": "", "trsnmDptyDcdNm": "", "stckStacMd": "12", "dvdnBasDt": "20260630",
            "cashDvdnPayDt": "20260828", "stckHndvDt": "", "stckDvdnRcd": "02", "stckDvdnRcdNm": "현금배당",
            "stckGenrDvdnAmt": "374", "stckGrdnDvdnAmt": "0", "stckGenrCashDvdnRt": "374",
            "stckGenrDvdnRt": "0", "cashGrdnDvdnRt": "0", "stckGrdnDvdnRt": "0"}
    base.update(kw)
    return base


class DividendsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_build(self):
        write_day(self.root / "raw" / "dividends" / "20261009.csv.gz", [
            row(),
            row(dvdnBasDt="20260930", cashDvdnPayDt="", stckGenrDvdnAmt="0", stckGenrCashDvdnRt="0"),
            row(isinCd="KR7000070003", isinCdNm="삼양홀딩스", stckParPrc="5000", dvdnBasDt="19930630",
                stckGenrDvdnAmt="0", stckGenrCashDvdnRt="12"),
            row(dvdnBasDt="19990630", stckDvdnRcd="04", stckDvdnRcdNm="무배당", stckGenrDvdnAmt="0"),
        ])
        self.assertEqual(dividends.build_dividends(self.root), 3)
        lines = (self.root / "dividends.csv").read_text(encoding="utf-8").splitlines()
        # Sorted by record date; the no-dividend record is dropped.
        self.assertTrue(lines[1].startswith("000070,KR7000070003,삼양홀딩스,보통주,12,19930630,"))
        # Only a rate given: no amount is derived from rate x (current) par.
        self.assertIn(",cash,,,12,0,5000", lines[1])
        self.assertEqual(lines[2], "005930,KR7005930003,삼성전자,보통주,12,20260630,20260828,,cash,374,,374,0,100")
        self.assertIn(",20260930,,,cash,,,0,0,100", lines[3])  # not announced yet

    def test_scrape_pages_and_keeps_latest_snapshot(self):
        old = self.root / "raw" / "dividends" / "20200101.csv.gz"
        write_day(old, [row()])
        bodies = [{"items": {"item": [row(), row(dvdnBasDt="20250630")]}, "totalCount": 3},
                  {"items": {"item": row(dvdnBasDt="20240630")}, "totalCount": 3}]  # single row = object
        with mock.patch.object(dividends, "fetch_page", side_effect=lambda s, k, p: bodies[p - 1]):
            path = dividends.scrape_dividends("key", self.root, max_age_days=0)
        self.assertEqual(path.name, "20261009.csv.gz")
        self.assertFalse(old.exists())
        self.assertEqual(dividends.build_dividends(self.root), 3)

    def test_recent_snapshot_skips_download(self):
        write_day(self.root / "raw" / "dividends" / "20261009.csv.gz", [row()])
        with mock.patch.object(dividends, "fetch_all", side_effect=AssertionError("should not download")):
            self.assertEqual(dividends.scrape_dividends("key", self.root).name, "20261009.csv.gz")
        with mock.patch.object(dividends, "fetch_all", return_value=[row(basDt="20261010")]):
            self.assertEqual(dividends.scrape_dividends("key", self.root, max_age_days=0).name, "20261010.csv.gz")

    def test_gateway_error_is_reported(self):
        resp = mock.Mock()
        resp.json.return_value = {"OpenAPI_ServiceResponse": {"cmmMsgHeader": {
            "errMsg": "SERVICE_KEY_IS_NOT_REGISTERED_ERROR", "returnAuthMsg": "등록되지 않은 서비스키"}}}
        session = mock.Mock(get=mock.Mock(return_value=resp))
        with self.assertRaisesRegex(dividends.DividendApiError, "SERVICE_KEY_IS_NOT_REGISTERED"):
            dividends.fetch_page(session, "bad", 1)


if __name__ == "__main__":
    unittest.main()
