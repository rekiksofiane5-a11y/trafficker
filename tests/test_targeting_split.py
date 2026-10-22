"""Plan UPSA (premier test réel) : bloc d'en-tête, dates en toutes lettres, plusieurs ciblages
dans une cellule -> un emplacement et un package par ciblage."""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "web"))
sys.path.insert(0, os.path.join(ROOT, "tests", "fixtures"))

import plan_agent  # noqa: E402


@pytest.mark.parametrize("text,expected", [
    ("16 au 23 avril 2025", ("2025-04-16", "2025-04-23")),
    ("du 28 mars au 4 avril 2025", ("2025-03-28", "2025-04-04")),
    ("1er - 15 mai 2026", ("2026-05-01", "2026-05-15")),
    ("du 20 décembre au 10 janvier 2027", ("2026-12-20", "2027-01-10")),
    ("02/11 au 15/12/2026", ("2026-11-02", "2026-12-15")),
])
def test_periods_in_words(text, expected):
    assert plan_agent.parse_period(text) == expected


def test_split_targeting_upsa_cell():
    from make_upsa import TARGETING
    segs = plan_agent.split_targeting(TARGETING)
    assert [s[0] for s in segs] == ["Socio-démo", "Contextuel", "Concurrents", "Comportemental"]
    assert segs[0][1] == "H/F – 18-49 ans"
    assert segs[1][1].startswith("Ballonnements repas")          # « (ciblage des mots clés...) : » retiré
    assert "Gaviscon" in segs[2][1]


def test_single_targeting_untouched():
    assert plan_agent.split_targeting("CSP+ 25-49 ans") == [("CSP+ 25-49 ans", "")]
    assert plan_agent.split_targeting("Ciblage : affinité sport") == [("Ciblage : affinité sport", "")]


def test_upsa_plan_granularity(tmp_path):
    pytest.importorskip("openpyxl")
    from make_upsa import build
    import web_api
    path = tmp_path / "upsa.xlsx"
    build(str(path))
    d = json.loads(web_api.analyze(str(path), "", "", "", ""))
    assert not d.get("fatal") and d["errors"] == []
    assert d["campaign"]["campaign_name"] == "Citrate programmatique 2025"
    assert d["campaign"]["advertiser_name"] == "UPSA"
    assert (d["campaign"]["campaign_start"], d["campaign"]["campaign_end"]) == ("2025-04-16", "2025-04-23")
    assert d["rows"] == 16                                         # 4 formats IAB x 4 ciblages
    packages = [r["name"] for r in d["preview"] if r["kind"] == "package"]
    assert len(packages) == 4 and any("CONTEXTUEL" in p for p in packages)
    assert any(c["key"] == "targeting_detail" for c in d["columns"])
    assert {r["size"] for r in d["table"]} == {"300x250", "160x600", "728x90", "300x600"}
