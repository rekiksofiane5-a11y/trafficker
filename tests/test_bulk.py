import os

import pytest

import cm360_bulk as bulk
from cm360_trafficker import (
    _read_rows, load_rows_from_path, normalize_header, plan_from_rows,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(ROOT, "plan_media_template.csv")
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "campaign_spreadsheet_vide.xls")


def test_headers_match_real_cm360_export():
    xlrd = pytest.importorskip("xlrd")
    sh = xlrd.open_workbook(FIXTURE).sheet_by_index(0)
    real = [str(sh.cell_value(0, c)) for c in range(sh.ncols)]
    assert bulk.BULK_HEADERS == real and len(real) == 72


def test_every_used_key_exists_in_headers():
    normalized = {normalize_header(h) for h in bulk.BULK_HEADERS}
    assert set(bulk.K.values()) <= normalized


def test_xls_header_only_file_is_detected_and_empty():
    pytest.importorskip("xlrd")
    assert _read_rows(FIXTURE) == []


def _plan_from_template():
    return plan_from_rows(load_rows_from_path(TEMPLATE))[0]


def test_export_has_one_line_per_assignment(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    out = tmp_path / "bulk.xlsx"
    n = bulk.write_bulk_xlsx(_plan_from_template(), str(out))
    ws = openpyxl.load_workbook(out).active
    assert ws.title == bulk.BULK_SHEET
    assert [c.value for c in ws[1]] == bulk.BULK_HEADERS
    assert ws.max_row == n + 1 == 7
    types = {ws.cell(r, bulk._COL["Type\n(Creative)"] + 1).value for r in range(2, ws.max_row + 1)}
    assert {"Tracking", "In-stream video", "Image", "Redirect"} <= types


def test_tracking_ad_exported_as_tracking_type():
    rows = bulk.plan_to_bulk_rows(_plan_from_template())
    ad_types = {r[bulk._COL["Ad name\n(Ad)"]]: r[bulk._COL["Type\n(Ad)"]] for r in rows}
    assert ad_types["Ad_Printemps_Tracking"] == "Tracking"
    assert ad_types["Ad_Printemps_300x250"] == "Standard"


def test_roundtrip_tracking_only_plan(tmp_path):
    pytest.importorskip("openpyxl")
    plan = _plan_from_template()
    camp = next(iter(plan.values()))
    camp.ads = {k: v for k, v in camp.ads.items() if k == "Ad_Printemps_Tracking"}
    out = tmp_path / "bulk.xlsx"
    bulk.write_bulk_xlsx(plan, str(out))
    rows = load_rows_from_path(str(out), "Printemps_2026_FR", "Client XYZ")
    plan2, errors = plan_from_rows(rows)
    assert errors == []
    c2 = next(iter(plan2.values()))
    assert (c2.start, c2.end) == ("2026-11-02", "2026-12-15")
    assert c2.ads["Ad_Printemps_Tracking"]["creatives"][0].ctype == "TRACKING"


def test_import_without_campaign_name_is_reported(tmp_path):
    pytest.importorskip("openpyxl")
    out = tmp_path / "bulk.xlsx"
    bulk.write_bulk_xlsx(_plan_from_template(), str(out))
    _, errors = plan_from_rows(load_rows_from_path(str(out)))
    assert any("campaign_name manquant" in e for e in errors)


def test_import_maps_budget_units_and_dates():
    H = {k: "" for k in bulk.K.values()}
    base = dict(H, **{bulk.K["placement"]: "P1", bulk.K["dims"]: "300 x 250",
                      bulk.K["start"]: "02/11/2026", bulk.K["end"]: "2026-12-15 00:00",
                      bulk.K["cost_structure"]: "CPM", bulk.K["units"]: "500000",
                      bulk.K["cost"]: "4 000,50", bulk.K["ad"]: "A",
                      bulk.K["creative"]: "C", bulk.K["ctype"]: "Tracking",
                      bulk.K["ct_url"]: "https://x.fr"})
    rows = bulk.bulk_to_plan_rows([base, dict(base, **{bulk.K["creative"]: "C2"})], "Camp", "Adv")
    assert rows[0]["campaign_start"] == "2026-11-02" and rows[0]["campaign_end"] == "2026-12-15"
    assert rows[0]["size"] == "300x250"
    # unités et coût comptés une fois par placement, portés par la première ligne
    assert rows[0]["objective_impressions"] == "500000" and rows[0]["budget_eur"] == "4000.5"
    assert rows[1]["objective_impressions"] == ""
    plan, errors = plan_from_rows(rows)
    assert errors == []
