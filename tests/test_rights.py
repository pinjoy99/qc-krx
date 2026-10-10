import tempfile
import unittest
from pathlib import Path
from unittest import mock

from qc_krx import rights
from qc_krx.krx_api import read_day, write_day


def ev(rcd, rcd_nm, kind, kind_nm, start, bas="20100101", crno="1101110012560", name="보령제약"):
    return {"basDt": bas, "issuCmpyKsdCustNo": "385", "crno": crno, "stckIssuCmpyNm": name, "stckParPrc": "500",
            "stckIssuRcd": rcd, "stckIssuRcdNm": rcd_nm, "rgtExertRcdNm": kind_nm, "rgtExertSttgDt": start,
            "rgtExertEdDt": start, "trsnmDptyDcd": "", "trsnmDptyDcdNm": "", "stckStacMd": "1231",
            "nmlsLckSttgDt": "", "nmlsLckEdDt": "", "scrsIssuMnbdCd": "", "scrsIssuMnbdCdNm": "", "rgtExertRcd": kind}


class RightsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_scrape_resumes_and_combines_pages(self):
        pages = {1: [ev("102", "무상증자", "01", "기준일", "20100101")],
                 2: [ev("102", "무상증자", "06", "상장일", "20100125")],
                 3: [ev("103", "액면분할", "01", "기준일", "20180401", bas="20180401")]}
        body = lambda p: {"items": {"item": pages[p] if p != 3 else pages[p][0]}, "totalCount": 20001}
        calls = []

        def fake(s, k, p):
            calls.append(p)
            if p == 3 and calls.count(3) == 1:
                raise rights.RightsApiError("connection reset")
            return body(p)

        with mock.patch.object(rights, "fetch_page", side_effect=fake):
            with self.assertRaises(rights.RightsApiError):
                rights.scrape_rights("k", self.root)
            path = rights.scrape_rights("k", self.root)  # resumes: page 2 isn't fetched again
        self.assertEqual(calls, [1, 2, 3, 1, 3])
        self.assertEqual(len(read_day(path)), 3)
        self.assertFalse((self.root / "raw" / "rights" / ".partial").exists())

    def test_build_corporate_actions(self):
        write_day(self.root / "raw" / "rights" / "20261010.csv.gz", [
            ev("102", "무상증자", "01", "기준일", "20100101"),
            ev("102", "무상증자", "03", "권리락일", "20091230"),
            ev("102", "무상증자", "06", "상장일", "20100125"),
            ev("102", "무상증자", "04", "명부폐쇄기간", "20100102"),
            ev("103", "액면분할", "01", "기준일", "20180401", bas="20180401", crno="999", name="삼성전자"),
        ])
        write_day(self.root / "raw" / "dividends" / "20261009.csv.gz", [
            {"crno": "1101110012560", "isinCd": "KR7003851004", "scrsItmsKcdNm": "우선주"},
            {"crno": "1101110012560", "isinCd": "KR7003850006", "scrsItmsKcdNm": "보통주"},
            {"crno": "999", "isinCd": "KR7005930003", "scrsItmsKcdNm": "보통주"},
        ])
        self.assertEqual(rights.build_corporate_actions(self.root), 2)
        lines = (self.root / "corporate_actions.csv").read_text(encoding="utf-8").splitlines()
        self.assertTrue(lines[0].startswith("code,crno,company,type,type_ko,base_date,record_date,ex_date,listing_date"))
        # Common share's code wins over the preferred one; dates are pivoted into columns.
        self.assertTrue(lines[1].startswith("003850,1101110012560,보령제약,bonus_issue,무상증자,20100101,20100101,20091230,20100125,"))
        self.assertTrue(lines[2].startswith("005930,999,삼성전자,split,액면분할,20180401,20180401,,"))


if __name__ == "__main__":
    unittest.main()
