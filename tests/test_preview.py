"""Aperçu « comme dans CM360 » : Campagne > Site > Package > Emplacement > Annonce > Créative."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web"))
import web_api
from cm360_trafficker import plan_from_rows

ROWS = [
    {"campaign_name": "Hiver", "campaign_start": "2026-10-08", "campaign_end": "2027-11-08",
     "site_name": "Teads FR", "package": "Package-TEADS-AwarenessDisplay", "placement_name": "P-3D",
     "size": "1x1", "ad_name": "A-3D", "creative_name": "K-3D", "landing_page_url": "https://x.fr"},
    {"campaign_name": "Hiver", "campaign_start": "2026-10-08", "campaign_end": "2027-11-08",
     "site_name": "Teads FR", "package": "Package-TEADS-AwarenessDisplay", "placement_name": "P-Cine",
     "size": "1x1", "ad_name": "A-Cine", "creative_name": "K-Cine", "landing_page_url": "https://x.fr"},
    {"campaign_name": "Hiver", "campaign_start": "2026-10-08", "campaign_end": "2027-11-08",
     "site_name": "Le Monde", "placement_name": "Home", "size": "300x250", "ad_name": "A-Home",
     "creative_name": "K-Home", "creative_path": "ban.png", "landing_page_url": "https://x.fr"},
]


def test_tree_order_levels_and_columns():
    plan, errors = plan_from_rows([dict(r) for r in ROWS])
    assert errors == []
    rows = web_api.preview(plan)
    shape = [(r["level"], r["kind"], r["name"]) for r in rows]
    assert shape == [
        (0, "campaign", "Hiver"),
        (1, "site", "Teads FR"),
        (2, "package", "Package-TEADS-AwarenessDisplay"),
        (3, "placement", "P-3D"), (4, "ad", "A-3D"), (5, "creative", "K-3D"),
        (3, "placement", "P-Cine"), (4, "ad", "A-Cine"), (5, "creative", "K-Cine"),
        (1, "site", "Le Monde"),
        (2, "placement", "Home"), (3, "ad", "A-Home"), (4, "creative", "K-Home"),
    ]
    p3d = rows[3]
    assert (p3d["start"], p3d["end"], p3d["type"], p3d["compatibility"], p3d["dimensions"]) == \
        ("08/10/2026", "08/11/2027", "Placement", "Display", "1 × 1")
    assert rows[4]["type"] == "Tracking" and rows[4]["end"] == "08/11/2027 23:59"
    assert rows[5]["type"] == "Tracking" and rows[5]["dimensions"] == ""
    assert rows[12]["type"] == "Image" and rows[12]["asset_type"] == "Image" and rows[12]["dimensions"] == "300 × 250"
    assert rows[11]["type"] == "Standard"


def test_missing_site_and_dates_flagged():
    rows = [{k: v for k, v in ROWS[2].items() if k not in ("site_name", "campaign_start", "campaign_end")}]
    plan, errors = plan_from_rows(rows, allow_incomplete=True)
    tree = web_api.preview(plan)
    assert tree[1]["kind"] == "site" and tree[1]["missing"] and tree[1]["name"] == "Site à compléter"
    assert tree[2]["start"] == ""


def test_rebuild_after_edit_updates_preview():
    import json
    import ingest
    rows = ingest.IngestedRows([dict(ROWS[2], objective="", site_name="Le Monde")])
    web_api._STATE.clear()
    d = json.loads(web_api._build([dict(r) for r in rows], "", "", []))
    assert [r["name"] for r in d["preview"] if r["kind"] == "placement"] == ["Home"]
    table = d["table"]
    table[0].update(objective="Notoriété", audience="25-49", format_label="Pavé", size="",
                    campaign_start="02/11/2026")
    d2 = json.loads(web_api.rebuild(json.dumps(table)))
    names = [r["name"] for r in d2["preview"] if r["kind"] == "placement"]
    assert names == ["NOTORIETE-25-49-LE_MONDE-PAVE"]               # nomenclature recalculée
    pl = [r for r in d2["preview"] if r["kind"] == "placement"][0]
    assert pl["dimensions"] == "300 × 250" and pl["start"] == "02/11/2026"
    assert {c["key"] for c in d2["columns"]} >= {"objective", "audience", "format_label"}


def test_package_per_regie_and_objective_and_devices():
    import json
    rows = [dict(ROWS[2], placement_name="Home", objective="Notoriété", device="Mobile"),
            dict(ROWS[2], placement_name="Home2", objective="Notoriété", device="Desktop"),
            dict(ROWS[2], placement_name="Art", objective="Trafic", ad_name="A2", creative_name="K2")]
    web_api._STATE.clear()
    d = json.loads(web_api._build(rows, "", "", []))
    tree = [(r["level"], r["kind"], r["name"]) for r in d["preview"]]
    pk = [n for lvl, k, n in tree if k == "package"]
    assert pk == ["PACKAGE-LE_MONDE-NOTORIETE", "PACKAGE-LE_MONDE-TRAFIC"]
    assert {c["key"] for c in d["columns"]} >= {"device", "objective"}
    assert "campaign_name" not in {c["key"] for c in d["columns"]}           # saisi en en-tête
    assert d["campaign"]["campaign_name"] == "Hiver"


def test_adform_preview_line_items_banners_tags():
    import ingest
    rows = [dict(ROWS[2], site_name="Amnet", line_budget_eur="151619", line_volume="11544211"),
            dict(ROWS[0])]
    plan, errors = plan_from_rows(rows)
    pa = web_api.preview_adform(plan)
    kinds = [r["kind"] for r in pa["campaign"]]
    assert kinds == ["campaign", "lineitem", "lineitem"]
    li = pa["campaign"][1]
    assert (li["media"], li["type"], li["sub"], li["budget"], li["volume"]) == \
        ("Amnet", "Direct", "Direct Line Item", "151 619,00 €", "11 544 211 Imps")
    assert {b["type"] for b in pa["banners"]} == {"Image", "Tracking (1x1)"}
    assert {t["tag_type"] for t in pa["tags"]} == {"Adform tag", "Tracking (1x1)"}


def test_short_sheet_name_not_used_as_campaign(tmp_path):
    import openpyxl
    from cm360_trafficker import load_rows_from_path
    wb = openpyxl.Workbook()
    wb.active.title = "OBJ"
    for r in [["Emplacement", "Format", "URL"], ["Home", "Pavé", "https://x.fr"]]:
        wb.active.append(r)
    wb.save(tmp_path / "Plan_Hiver_2026.xlsx")
    rows = load_rows_from_path(str(tmp_path / "Plan_Hiver_2026.xlsx"))
    assert rows[0]["campaign_name"] == "Plan Hiver 2026"


def test_ads_are_placement_x_creative_with_override():
    import json
    rows = [dict(ROWS[2], placement_name="Home", creative_name="Soldes"),
            dict(ROWS[2], placement_name="Home", creative_name="Noel", ad_name="A-Home"),
            dict(ROWS[2], placement_name="Art", creative_name="Soldes", ad_name="A-Art", ad_final="PERSO")]
    web_api._STATE.clear()
    d = json.loads(web_api._build(rows, "", "", []))
    ads = [r["name"] for r in d["preview"] if r["kind"] == "ad"]
    assert ads == ["Home-Soldes", "Home-Noel", "PERSO"]
    pl = [r for r in d["preview"] if r["kind"] == "placement"]
    assert pl[0]["rows"] == [0, 1] and pl[0]["edit"] == "placement_final"


def test_forced_placement_name_wins():
    import json
    rows = [dict(ROWS[2], objective="Notoriété", placement_final="MON-NOM")]
    web_api._STATE.clear()
    d = json.loads(web_api._build(rows, "", "", []))
    assert [r["name"] for r in d["preview"] if r["kind"] == "placement"] == ["MON-NOM"]


def test_instructions_are_applied_or_noted():
    rows = [{"placement_name": "Home", "site_name": "", "landing_page_url": ""},
            {"placement_name": "Art", "site_name": "Le Monde", "landing_page_url": "https://a.fr"}]
    report = []
    web_api.apply_instructions(rows, "Campagne : Hiver 2026\nPériode : du 02/11 au 15/12/2026\n"
                                     "URL : https://x.fr\nRégie : Teads\nmerci de vérifier les formats", report)
    assert all(r["campaign_name"] == "Hiver 2026" and r["campaign_start"] == "2026-11-02"
               and r["campaign_end"] == "2026-12-15" for r in rows)
    assert rows[0]["landing_page_url"] == "https://x.fr" and rows[1]["landing_page_url"] == "https://a.fr"
    assert rows[0]["site_name"] == "Teads" and rows[1]["site_name"] == "Le Monde"
    assert sum("appliquée" in l for l in report) == 4 and any("non interprétée" in l for l in report)
