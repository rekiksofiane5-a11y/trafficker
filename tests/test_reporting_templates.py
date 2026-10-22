"""Templates de reporting : check de mise en ligne et report régie (données ad server ou démo)."""
import io
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import reporting  # noqa: E402

CAMPAIGN = {"id": "1", "name": "Campagne test", "advertiser": "Annonceur", "start": "2026-10-01", "end": "2026-10-31"}
PLACEMENTS = [
    {"id": "11", "name": "LM-PAVE", "site": "Le Monde", "site_id": "5", "size": "300x250"},
    {"id": "12", "name": "LM-GA", "site": "Le Monde", "site_id": "5", "size": "300x600"},
    {"id": "21", "name": "TEADS-VIDEO", "site": "Teads", "site_id": "6", "size": "640x360"},
    {"id": "31", "name": "FIG-PAVE", "site": "Le Figaro", "site_id": "7", "size": "300x250", "start": "2026-11-05"},
]
DELIVERY = [
    {"date": "2026-10-01", "placement_id": "11", "impressions": 1000, "clicks": 3},
    {"date": "2026-10-02", "placement_id": "11", "impressions": 2000, "clicks": 1},
    {"date": "2026-10-02", "placement_id": "21", "impressions": 500, "clicks": 0},
]


def test_check_status_per_placement_and_site():
    c = reporting.check(CAMPAIGN, PLACEMENTS, DELIVERY, "2026-10-10")
    st = {p["id"]: p["status"] for p in c["placements"]}
    assert st == {"11": reporting.LIVE, "12": reporting.NO_DATA, "21": reporting.LIVE, "31": reporting.NOT_STARTED}
    sites = {s["site"]: s["status"] for s in c["sites"]}
    assert sites == {"Le Monde": "Partiel", "Teads": reporting.LIVE, "Le Figaro": reporting.NOT_STARTED}
    k = c["kpis"]
    assert (k["impressions"], k["clicks"], k["placements_live"], k["sites_live"]) == (3500, 4, 2, 2)
    assert (k["first"], k["last"], k["days"]) == ("2026-10-01", "2026-10-02", 2)
    lm = next(p for p in c["placements"] if p["id"] == "11")
    assert lm["ctr"] == round(4 / 3000 * 100, 2) and lm["first"] == "2026-10-01"


def test_regie_report_only_its_placements_with_total():
    r = reporting.regie_report(CAMPAIGN, PLACEMENTS, DELIVERY, "Le Monde")
    assert [row[1] for row in r["rows"]] == ["LM-PAVE", "LM-PAVE"]
    assert r["total"][4:6] == [3000, 4] and r["placements"] == 2 and r["placements_live"] == 1


def test_excel_exports():
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.load_workbook(io.BytesIO(reporting.export_check(CAMPAIGN, PLACEMENTS, DELIVERY, "2026-10-10")))
    assert wb.sheetnames == ["Synthèse", "Par régie", "Emplacements", "Données jour"]
    values = [c.value for row in wb["Emplacements"].iter_rows() for c in row]
    assert "Aucune donnée" in values and "TEADS-VIDEO" in values
    wb = openpyxl.load_workbook(io.BytesIO(reporting.export_regie(CAMPAIGN, PLACEMENTS, DELIVERY, "Teads", "2026-10-10")))
    values = [c.value for row in wb["Diffusion"].iter_rows() for c in row]
    assert "TEADS-VIDEO" in values and "LM-PAVE" not in values and "Total" in values


def test_demo_delivery_is_deterministic_and_leaves_gaps():
    data = json.load(open(os.path.join(ROOT, "web", "demo_adserver.json"), encoding="utf-8"))
    camp = data["campaigns"][1]
    c = {"id": camp["id"], "name": camp["name"], "start": "2026-10-01", "end": "2026-11-30"}
    a = reporting.demo_delivery(c, camp["placements"], "2026-10-22")
    assert a == reporting.demo_delivery(c, camp["placements"], "2026-10-22")
    check = reporting.check(c, camp["placements"], a, "2026-10-22")
    assert 0 < check["kpis"]["placements_live"] < check["kpis"]["placements"]      # le check a des trous à montrer
    assert all(r["date"] < "2026-10-22" for r in a)
