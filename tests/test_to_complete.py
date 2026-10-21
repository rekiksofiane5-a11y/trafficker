"""Informations introuvables : laissées vides, listées « à compléter », jamais envoyées."""
import pytest

from cm360_trafficker import build_adapter, plan_from_rows, plan_gaps, traffic_plan

ROWS = [{"campaign_name": "Hiver", "placement_name": "Home", "size": "300x250", "ad_name": "A1",
         "creative_name": "K1"},
        {"campaign_name": "Hiver", "placement_name": "Article", "size": "728x90", "ad_name": "A2",
         "creative_name": "K2", "landing_page_url": "https://x.fr"}]


def test_missing_values_are_gaps_not_errors():
    plan, errors = plan_from_rows([dict(r) for r in ROWS], allow_incomplete=True)
    assert errors == []
    gaps = plan_gaps(plan)
    assert "Date de début — à compléter : campagne « Hiver »" in gaps
    assert "Date de fin — à compléter : campagne « Hiver »" in gaps
    assert "URL de destination — à compléter : A1" in gaps
    camp = next(iter(plan.values()))
    assert camp.start == "" and camp.ads["A1"]["landing_page_url"] == ""


def test_strict_mode_unchanged():
    _, errors = plan_from_rows([dict(r) for r in ROWS])
    assert errors


def test_unreadable_values_are_left_empty_too():
    rows = [dict(ROWS[1], campaign_start="32/13/2026", campaign_end="2026-12-15")]
    plan, errors = plan_from_rows(rows, allow_incomplete=True)
    assert errors == []
    assert any("valeur illisible « 32/13/2026 »" in g for g in plan_gaps(plan))
    rows = [dict(ROWS[1], campaign_start="2026-12-15", campaign_end="2026-11-02")]
    plan, errors = plan_from_rows(rows, allow_incomplete=True)
    assert errors == [] and any("avant début" in g for g in plan_gaps(plan))
    _, strict = plan_from_rows(rows)                          # mode strict : toujours bloquant
    assert strict


def test_date_found_on_another_line_fills_the_campaign():
    rows = [dict(ROWS[0]), dict(ROWS[1], campaign_start="2026-11-02", campaign_end="2026-12-15")]
    plan, errors = plan_from_rows(rows, allow_incomplete=True)
    assert errors == []
    assert next(iter(plan.values())).start == "2026-11-02"
    assert plan_gaps(plan) == ["URL de destination — à compléter : A1"]


def test_real_send_is_blocked_demo_is_flagged():
    plan, _ = plan_from_rows([dict(r) for r in ROWS], allow_incomplete=True)
    logs = []
    traffic_plan(build_adapter("mock", log=logs.append), plan, log=logs.append)
    assert any("[À COMPLÉTER]" in l for l in logs)

    class Real:                              # tout adaptateur réel (CM360, Adform)
        name = "cm360"
        report = {"created": {}, "reused": {}, "errors": []}
        def __getattr__(self, _):
            raise AssertionError("aucun appel à l'ad server attendu")
    real = Real()
    report = traffic_plan(real, plan, log=lambda m: None)
    assert report["errors"] and "à compléter" in report["errors"][0]


def test_exports_keep_empty_cells(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    import adform_bulk
    import cm360_bulk
    plan, _ = plan_from_rows([dict(r) for r in ROWS], allow_incomplete=True)
    cm360_bulk.write_bulk_xlsx(plan, str(tmp_path / "c.xlsx"))
    ws = openpyxl.load_workbook(tmp_path / "c.xlsx").active
    col = cm360_bulk._COL["Start date\n(Placement)"] + 1
    assert ws.cell(2, col).value in (None, "")
    adform_bulk.write_adform_bulk(plan, str(tmp_path / "a.xlsx"))
    assert openpyxl.load_workbook(tmp_path / "a.xlsx")["Campaigns"]["G5"].value is None
