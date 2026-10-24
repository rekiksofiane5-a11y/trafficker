import os
from datetime import date

import pytest

from cm360_trafficker import (
    apply_nomenclature, build_adapter, load_nomenclature, load_rows_from_path,
    plan_from_rows, traffic_plan,
)
from cm360_reporting import (
    CampaignDelivery, MockReportingAdapter, extract_budgets, reconcile,
    report_for_plan, delivery_to_dict,
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
    assert set(camp.placements) == {"BN_Home_300x250", "BN_Home_728x90", "VID_Preroll_640x360"}
    assert len(camp.ads) == 5


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
    assert len(d.placements) == 3
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


# --- Typage des créatives ----------------------------------------------------

from cm360_trafficker import resolve_creative_type


@pytest.mark.parametrize("explicit,category,snippet,path,expected,auto", [
    ("", "", "<script>", "", "REDIRECT", False),       # tag tiers
    ("", "", "", "ban.png", "IMAGE", False),           # fichier image -> display
    ("", "", "", "spot.MP4", "VIDEO", False),          # fichier vidéo -> in-stream
    ("", "", "", "", "TRACKING", True),                # rien de partagé -> tracking auto
    ("", "video", "", "fichier.bin", "VIDEO", False),  # catégorie forcée
    ("tracking", "", "<script>", "", "TRACKING", False),  # type explicite prioritaire
    ("instream", "", "", "spot.mp4", "VIDEO", False),  # alias
])
def test_resolve_creative_type(explicit, category, snippet, path, expected, auto):
    assert resolve_creative_type(explicit, category, snippet, path)[:2] == (expected, auto)


def test_unknown_file_format_is_rejected():
    assert resolve_creative_type("", "", "", "brief.docx")[2]


def test_template_types(rows):
    plan, _ = plan_from_rows(rows)
    camp = next(iter(plan.values()))
    types = {c.name: (c.ctype, c.auto) for ad in camp.ads.values() for c in ad["creatives"]}
    assert types["Crea_Video_15s"] == ("VIDEO", False)
    assert types["Crea_Tracking_A"] == ("TRACKING", True)
    assert types["Crea_300x250_PNG"] == ("IMAGE", False)
    assert types["Crea_300x250_A"] == ("REDIRECT", False)


def test_ad_cannot_mix_tracking_and_display(rows):
    bad = [dict(r) for r in rows]
    extra = dict(bad[0]); extra["creative_name"] = "Crea_Track_Mix"
    extra["snippet"] = ""; extra["creative_type"] = ""                      # sans tag ni fichier -> tracking, dans une annonce display
    _, errors = plan_from_rows(bad + [extra])
    assert any("mélange" in e for e in errors)


def test_mock_logs_creative_categories(rows):
    plan, _ = plan_from_rows(rows)
    logs = []
    traffic_plan(build_adapter("mock", log=logs.append), plan, log=logs.append)
    text = "\n".join(logs)
    assert "VIDEO in-stream" in text and "TRACKING auto" in text and "IMAGE display" in text


# --- Corps des requêtes CM360 (service factice : aucune validation API réelle) ---

class _FakeSvc:
    """Enregistre les corps envoyés à creatives().insert / ads().insert."""
    def __init__(self):
        self.sent = {}

    def _res(self, name):
        outer = self

        class R:
            def list(self, **kw):
                return type("X", (), {"execute": lambda s: {}})()

            def insert(self, **kw):
                outer.sent.setdefault(name, []).append(kw)
                return type("X", (), {"execute": lambda s: {"id": 42, "assetIdentifier": {"name": "f", "type": "VIDEO"}}})()
        return R()

    def creatives(self): return self._res("creatives")
    def ads(self): return self._res("ads")
    def creativeAssets(self): return self._res("assets")
    def campaignCreativeAssociations(self): return self._res("assoc")


def _cm360(tmp_path):
    from cm360_trafficker import CM360Adapter
    svc = _FakeSvc()
    return CM360Adapter(svc, 1, log=lambda m: None, creatives_dir=str(tmp_path)), svc


def test_cm360_tracking_creative_body(tmp_path):
    from cm360_trafficker import CreativeSpec
    ad, svc = _cm360(tmp_path)
    ad.ensure_creative(1, 2, CreativeSpec(name="T", ctype="TRACKING", auto=True), 300, 250)
    body = svc.sent["creatives"][0]["body"]
    assert body["type"] == "TRACKING_TEXT" and "creativeAssets" not in body


def test_cm360_video_creative_is_instream(tmp_path, monkeypatch):
    pytest.importorskip("googleapiclient")
    from cm360_trafficker import CreativeSpec
    (tmp_path / "v.mp4").write_bytes(b"\0" * 16)
    ad, svc = _cm360(tmp_path)
    ad.ensure_creative(1, 2, CreativeSpec(name="V", ctype="VIDEO", path="v.mp4"), 640, 360)
    assert svc.sent["assets"][0]["body"]["assetIdentifier"]["type"] == "VIDEO"
    assert svc.sent["creatives"][0]["body"]["type"] == "INSTREAM_VIDEO"


def test_cm360_tracking_ad_type(tmp_path):
    from cm360_trafficker import CreativeSpec
    ad, svc = _cm360(tmp_path)
    t = CreativeSpec(name="T", ctype="TRACKING", auto=True)
    ad.ensure_ad(2, "A", {"creatives": [t], "landing_page_url": "https://x.fr"}, [1], {"T": 7})
    assert svc.sent["ads"][0]["body"]["type"] == "AD_SERVING_TRACKING"
    d = CreativeSpec(name="D", ctype="REDIRECT", snippet="<s>")
    ad.ensure_ad(2, "B", {"creatives": [d], "landing_page_url": "https://x.fr"}, [1], {"D": 8})
    assert svc.sent["ads"][1]["body"]["type"] == "AD_SERVING_STANDARD_AD"
