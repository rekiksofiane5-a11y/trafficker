import csv
import io
import os
from datetime import date

import pytest

from cm360_trafficker import (
    apply_nomenclature, build_adapter, load_nomenclature, load_rows_from_path,
    plan_from_rows, traffic_plan,
)
from cm360_reporting import (
    CampaignDelivery, MockReportingAdapter, extract_budgets, reconcile,
    report_for_plan, delivery_to_dict, extract_flights,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(ROOT, "plan_media_template.csv")


@pytest.fixture
def rows():
    return load_rows_from_path(TEMPLATE)


def test_template_is_valid(rows):
    plan, errors = plan_from_rows(rows)
    assert errors == []
    camp = next(iter(plan.values()))
    assert set(camp.placements) == {"BN_Home_300x250", "BN_Home_728x90"}
    assert len(camp.ads) == 3


def test_validation_errors(rows):
    bad = [dict(r) for r in rows]
    bad[0]["campaign_end"] = "2026-10-01"        # fin avant début
    bad[1]["size"] = "grand"                     # format invalide
    bad[2]["landing_page_url"] = ""              # URL manquante
    _, errors = plan_from_rows(bad)
    text = "\n".join(errors)
    assert "avant campaign_start" in text
    assert "size invalide" in text
    assert "landing_page_url manquant" in text


def test_impossible_date_is_rejected(rows):
    bad = [dict(r) for r in rows]
    bad[0]["campaign_start"] = "2026-13-45"
    _, errors = plan_from_rows(bad)
    assert any("date réelle" in e for e in errors)


def test_duplicate_row_is_rejected(rows):
    _, errors = plan_from_rows(rows + [dict(rows[0])])
    assert any("doublon" in e for e in errors)


def test_inconsistent_campaign_dates(rows):
    bad = [dict(r) for r in rows]
    bad[1]["campaign_end"] = "2026-12-31"
    _, errors = plan_from_rows(bad)
    assert any("incohérentes" in e for e in errors)


def test_mock_trafficking_runs_without_errors(rows):
    plan, _ = plan_from_rows(rows)
    logs = []
    report = traffic_plan(build_adapter("mock", log=logs.append), plan, log=logs.append)
    assert not any("[ERREUR]" in m for m in logs)
    assert report


def test_mock_trafficking_is_idempotent(rows):
    plan, _ = plan_from_rows(rows)
    adapter = build_adapter("mock", log=lambda m: None)
    traffic_plan(adapter, plan, log=lambda m: None)
    logs = []
    traffic_plan(adapter, plan, log=logs.append)
    assert not any("[ERREUR]" in m for m in logs)


def test_nomenclature_renames_before_send(rows):
    plan, _ = plan_from_rows(rows)
    naming = load_nomenclature(os.path.join(ROOT, "nomenclatures.json"))
    plan, renames = apply_nomenclature(plan, naming, log=lambda m: None)
    assert renames
    camp = next(iter(plan.values()))
    assert camp.name.startswith("XYZ_")
    # les annonces référencent bien les emplacements renommés
    for ad in camp.ads.values():
        for pname in ad["placements"]:
            assert pname in camp.placements


# --- Reporting ---------------------------------------------------------------

def test_mock_reporting_covers_placements(rows):
    deliveries, flags = report_for_plan(rows, MockReportingAdapter(log=lambda m: None))
    assert len(deliveries) == 1
    d = deliveries[0]
    assert len(d.placements) == 2
    assert sum(p.impressions for p in d.placements.values()) <= d.impressions
    assert d.spend > 0
    assert flags


def test_mock_reporting_is_deterministic(rows):
    a, _ = report_for_plan(rows, MockReportingAdapter(log=lambda m: None))
    b, _ = report_for_plan(rows, MockReportingAdapter(log=lambda m: None))
    assert (a[0].impressions, a[0].spend) == (b[0].impressions, b[0].spend)


FLIGHTS = {"C": ("2026-01-01", "2026-01-11", 1000)}   # 10 jours


@pytest.mark.parametrize("imps,status", [
    (500, "OK"),            # attendu à J5 = 500
    (200, "EN RETARD"),
    (900, "EN AVANCE"),
])
def test_impression_pacing(imps, status):
    d = CampaignDelivery(name="C", impressions=imps)
    line = reconcile([d], FLIGHTS, today=date(2026, 1, 6))[0]
    assert f"[{status}]" in line


def test_flight_not_started():
    d = CampaignDelivery(name="C", impressions=0)
    line = reconcile([d], FLIGHTS, today=date(2025, 12, 1))[0]
    assert "NON DÉMARRÉE" in line and "EN RETARD" not in line


def test_budget_pacing():
    d = CampaignDelivery(name="C", impressions=100, spend=500.0)
    line = reconcile([d], {"C": ("2026-01-01", "2026-01-11", None)},
                     today=date(2026, 1, 6), budgets={"C": 1000.0})[0]
    assert "pacing dépense 100%" in line and "[OK]" in line
    d.spend = 100.0
    line = reconcile([d], {"C": ("2026-01-01", "2026-01-11", None)},
                     today=date(2026, 1, 6), budgets={"C": 1000.0})[0]
    assert "[EN RETARD]" in line


def test_extract_budgets_formats():
    rows = [{"campaign_name": "A", "budget_eur": "4 000,50"},
            {"campaign_name": "B", "budget_eur": "n/a"},
            {"campaign_name": "C", "budget_eur": ""}]
    assert extract_budgets(rows) == {"A": 4000.5}


def test_delivery_json_has_spend(rows):
    deliveries, flags = report_for_plan(rows, MockReportingAdapter(log=lambda m: None))
    data = delivery_to_dict("mock", deliveries, flags)
    assert data["campaigns"][0]["spend"] > 0
    assert data["campaigns"][0]["placements"][0]["spend"] > 0
