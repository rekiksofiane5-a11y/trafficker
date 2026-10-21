import os

import pytest

openpyxl = pytest.importorskip("openpyxl")
import adform_bulk as ab
from cm360_trafficker import load_rows_from_path, plan_from_rows

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _plan():
    return plan_from_rows(load_rows_from_path(os.path.join(ROOT, "plan_media_template.csv")))[0]


def test_template_has_no_client_data():
    wb = openpyxl.load_workbook(ab.TEMPLATE)
    for n in ("Campaigns", "Orders"):
        assert all(c.value is None for c in wb[n][ab.FIRST_DATA_ROW])
    assert wb.sheetnames[:4] == ["Instructions", "Campaigns", "Orders", "Programmatic line items"]


def test_template_headers_match_guard():
    wb = openpyxl.load_workbook(ab.TEMPLATE)
    ab._check_headers(wb["Campaigns"], ab.CAMPAIGN_COLS, "Campaigns")
    ab._check_headers(wb["Orders"], ab.ORDER_COLS, "Orders")


def test_export_fills_campaign_and_order(tmp_path):
    out = tmp_path / "ad.xlsx"
    assert ab.write_adform_bulk(_plan(), str(out)) == 1
    wb = openpyxl.load_workbook(out)
    c, o = wb["Campaigns"], wb["Orders"]
    assert c["B5"].value == "Printemps_2026_FR" and c["C5"].value == "Non-programmatic"
    assert c["G5"].value.date().isoformat() == "2026-11-02" and c["R5"].value == 4000
    assert o["C5"].value == o["D5"].value == "Printemps_2026_FR"   # commande sous la campagne
    assert o["AC5"].value == 4000
    assert c["D5"].value == "EUR - Euro"
    assert wb.sheetnames == openpyxl.load_workbook(ab.TEMPLATE).sheetnames   # structure intacte


def test_forbidden_name_chars_rejected(tmp_path):
    plan = _plan()
    next(iter(plan.values())).name = "Camp<agne>?"
    with pytest.raises(ValueError):
        ab.write_adform_bulk(plan, str(tmp_path / "x.xlsx"))


def test_unknown_campaign_type_rejected(tmp_path):
    with pytest.raises(ValueError):
        ab.write_adform_bulk(_plan(), str(tmp_path / "x.xlsx"), "Inconnu")


def test_ui_adform_bulk_download():
    import cm360_trafficker_ui as ui
    c = ui.app.test_client()
    j = c.post("/analyze", data={"platform": "mock", "demo": "on",
               "plan": (open(os.path.join(ROOT, "plan_media_template.csv"), "rb"), "p.csv")},
               content_type="multipart/form-data").get_json()
    r = c.get(f"/adform-bulk/{j['token']}")
    assert r.status_code == 200 and r.data[:2] == b"PK"
