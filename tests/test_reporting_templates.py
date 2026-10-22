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


TARGETS = {"source": "Plan test", "campaign": {"impressions": "", "budget": ""}, "placements": [
    {"name": "lm pave", "impressions": "10000", "budget": "100"},            # même nom, casse / séparateurs différents
    {"name": "LM-GA", "impressions": "5000", "budget": "50"},
    {"name": "TEADS-VIDEO", "impressions": "1000", "budget": "20"},
    {"name": "ABSENT-DE-L-ADSERVER", "impressions": "999"},
]}


def test_pacing_planned_vs_delivered():
    # Campagne de 31 jours, données jusqu'au 09/10 : 9 jours écoulés
    c = reporting.check(CAMPAIGN, PLACEMENTS, DELIVERY, "2026-10-10", TARGETS)
    pc = c["pacing"]
    assert pc["available"] and pc["matched"] == 3 and pc["unmatched_plan"] == ["ABSENT-DE-L-ADSERVER"]
    lm = next(p for p in c["placements"] if p["id"] == "11")["pacing"]
    assert lm["expected"] == round(10000 * 9 / 31) and lm["delivered"] == 3000
    assert lm["pace"] == 103.3 and lm["pace_status"] == reporting.ON_TRACK      # 3000 livrées / 2903 prévues
    ga = next(p for p in c["placements"] if p["id"] == "12")["pacing"]
    assert ga["pace"] == 0 and ga["pace_status"] == reporting.LATE
    assert lm["spent"] == 30.0                                    # 3000 / 10000 x 100 €
    k = pc["kpis"]
    assert k["planned"] == 16000 and k["budget"] == 170 and k["level"] == "emplacements"
    assert {s["site"] for s in pc["sites"]} == {"Le Monde", "Teads"}


def test_pacing_campaign_level_and_absent():
    t = {"source": "Plan global", "campaign": {"impressions": "31000", "budget": "310"}, "placements": []}
    pc = reporting.check(CAMPAIGN, PLACEMENTS, DELIVERY, "2026-10-10", t)["pacing"]
    assert pc["kpis"]["level"] == "campagne" and pc["kpis"]["expected"] == 9000 and pc["kpis"]["delivered"] == 3500
    assert pc["kpis"]["pace_status"] == reporting.LATE
    none = reporting.check(CAMPAIGN, PLACEMENTS, DELIVERY, "2026-10-10", {"campaign": {}, "placements": []})["pacing"]
    assert not none["available"] and "ni volume ni budget" in none["reason"]
    assert reporting.check(CAMPAIGN, PLACEMENTS, DELIVERY, "2026-10-10")["pacing"] == {"available": False}


def test_pacing_sheet_in_excel():
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.load_workbook(io.BytesIO(reporting.export_check(CAMPAIGN, PLACEMENTS, DELIVERY, "2026-10-10", TARGETS)))
    assert "Rythme" in wb.sheetnames
    values = [c.value for row in wb["Rythme"].iter_rows() for c in row]
    assert reporting.LATE in values and "Total" in values
    syn = [c.value for row in wb["Synthèse"].iter_rows() for c in row]
    assert "Plan média lié" in syn


def test_split_line_shares_budget_and_volume(tmp_path):
    pytest.importorskip("openpyxl")
    sys.path.insert(0, os.path.join(ROOT, "web"))
    sys.path.insert(0, os.path.join(ROOT, "tests", "fixtures"))
    from make_upsa import build
    import web_api
    path = tmp_path / "upsa.xlsx"
    build(str(path), 1600000, "8 000 €")
    d = json.loads(web_api.analyze(str(path), "", "", "", ""))
    t = json.loads(web_api.plan_targets(json.dumps(d["table"]), "", "UPSA"))
    assert len(t["placements"]) == 16
    assert all(p["impressions"] == "100000" and p["budget"] == "500.00" for p in t["placements"])
    assert float(t["campaign"]["budget"]) == 8000 and t["campaign"]["impressions"] == "1600000"


def test_parse_cm360_export_file(tmp_path):
    """Mode fichier : export CM360 (en-têtes de rapport, « Report Fields », Grand Total) -> données du check."""
    import shutil
    src = os.path.join(ROOT, "web", "exemple_export_cm360.csv")
    path = tmp_path / "export.csv"
    shutil.copy(src, path)
    r = reporting.parse_export(str(path))
    assert r["campaign"]["name"] == "Citrate programmatique 2025" and r["campaign"]["advertiser"] == "UPSA"
    assert (r["campaign"]["start"], r["campaign"]["end"]) == ("2026-10-16", "2026-10-21")
    assert len(r["placements"]) == 12 and r["rows"] == 72 and r["warnings"] == []
    assert all(p["site"] == "DV360 Open Market" and p["size"] for p in r["placements"])
    c = reporting.check({**r["campaign"], "end": "2026-10-23"}, r["placements"], r["delivery"], "2026-10-22")
    assert c["kpis"]["impressions"] == 1747655 and c["kpis"]["placements_live"] == 12


def test_parse_export_variants_and_plan_placements(tmp_path):
    p = tmp_path / "instant.csv"
    p.write_text("Campaign,Site (CM360),Placement,Impressions,Clicks\n"
                 "Noël,Le Monde,LM-PAVE,\"1,200\",3\nNoël,Teads,TEADS-VIDEO,800,1\nAutre,Le Monde,X,5,0\n"
                 "Grand Total:,,,2005,4\n", encoding="utf-8")
    r = reporting.parse_export(str(p))
    assert r["campaign"]["name"] == "Noël" and r["campaigns"] == ["Noël", "Autre"]
    assert [d["impressions"] for d in r["delivery"]] == [1200, 800]
    assert any("Date" in w for w in r["warnings"]) and any("2 campagnes" in w for w in r["warnings"])
    # Plan lié : les emplacements absents de l'export (aucune diffusion) sont signalés
    targets = {"campaign": {}, "placements": [{"name": "LM-PAVE", "impressions": "1000"},
                                              {"name": "LM-GRAND-ANGLE", "site": "Le Monde", "impressions": "500"}]}
    camp = {**r["campaign"], "start": "2026-10-01", "end": "2026-10-31"}
    c = reporting.check(camp, r["placements"], r["delivery"], "2026-10-10", targets)
    missing = [x for x in c["placements"] if x["status"] == reporting.NO_DATA]
    assert [x["name"] for x in missing] == ["LM-GRAND-ANGLE"]
    with pytest.raises(ValueError):
        q = tmp_path / "autre.csv"
        q.write_text("a,b\n1,2\n", encoding="utf-8")
        reporting.parse_export(str(q))


def test_real_cm360_instant_report_xlsx(tmp_path):
    """Export Excel réel de CM360 (classeur non standard qui fait échouer openpyxl) : lu quand même,
    bloc d'en-tête exploité, clics sans impression comptés, absence de colonne Campaign signalée."""
    sys.path.insert(0, os.path.join(ROOT, "tests", "fixtures"))
    from make_cm360_export import build
    path = tmp_path / "query.xlsx"
    build(str(path))
    r = reporting.parse_export(str(path))
    assert r["rows"] == 4 and len(r["placements"]) == 3
    assert r["meta"]["account"] == "3021" and r["meta"]["timezone"] == "Europe/Paris"
    assert (r["campaign"]["start"], r["campaign"]["end"]) == ("2026-10-01", "2026-10-02")   # période du rapport
    assert any("Pas de colonne Campaign" in w for w in r["warnings"])
    assert any("clics sans impression" in w for w in r["warnings"])
    c = reporting.check(r["campaign"], r["placements"], r["delivery"], "2026-10-03")
    assert c["kpis"]["placements_live"] == 3                                                # click tracker compté
    build(str(path))
    f = reporting.parse_export(str(path), keyword="lemonde")
    assert [p["id"] for p in f["placements"]] == ["451000001"] and f["rows"] == 2


def test_export_table_types_and_pivot_excel(tmp_path):
    """Toutes les colonnes de l'export : dimensions / métriques / taux, Semaine et Mois ajoutés ; Excel du croisé."""
    openpyxl = pytest.importorskip("openpyxl")
    sys.path.insert(0, os.path.join(ROOT, "tests", "fixtures"))
    from make_cm360_export import build
    path = tmp_path / "query.xlsx"
    build(str(path))
    t = reporting.parse_export(str(path))["table"]
    kinds = {c["label"]: (c["kind"], c["rate"]) for c in t["columns"]}
    assert kinds["Placement ID"] == ("dimension", False) and kinds["Date"] == ("dimension", False)
    assert kinds["Impressions"] == ("metric", False) and kinds["Click Rate"] == ("metric", True)
    assert kinds["Semaine"][0] == "dimension" and kinds["Mois"][0] == "dimension"
    assert t["rows"][0][-2:] == ["S40 · 28/09/2026", "2026-10"] and len(t["rows"]) == 4
    wb = openpyxl.load_workbook(io.BytesIO(reporting.export_pivot(
        "Test", ["Site (CM360)", "Impressions"], [["Teads FR", 50000], ["Total", 229000]], t)))
    assert wb.sheetnames == ["Tableau croisé", "Données"]
    assert "Donnees" in wb["Données"].tables


def test_single_campaign_example_export(tmp_path):
    """Exemple livré : export Excel CM360 d'une seule campagne (Campaign / Campaign ID), nomenclature agence."""
    import shutil
    path = tmp_path / "one.xlsx"
    shutil.copy(os.path.join(ROOT, "web", "exemple_export_cm360_une_campagne.xlsx"), path)
    r = reporting.parse_export(str(path))
    assert r["campaign"]["name"].endswith("635419 (36649579)") and not r["account_wide"]
    assert r["campaign"]["start"] == "2026-09-14" and r["campaign"]["dates_from"] == "date en tête du nom de campagne"
    assert len(r["placements"]) == 9 and not any("Campaign" in w for w in r["warnings"])
