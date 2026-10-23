"""Trafficking sheet d'agence : nomenclature et vocabulaire lus dans le classeur, une ligne
d'emplacement par ciblage, une créative par message, VAST 0x0, achats via DSP."""
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "web"), os.path.join(ROOT, "tests")]

import agency_sheet  # noqa: E402
import web_api  # noqa: E402
from fixtures.make_agency_sheet import build  # noqa: E402


def _analyze(tmp_path):
    path = str(tmp_path / "pm_agence.xlsx")
    build(path)
    return json.loads(web_api.analyze(shutil.copy(path, str(tmp_path / "run.xlsx")))), path


def test_names_follow_the_workbook_convention(tmp_path):
    d, _ = _analyze(tmp_path)
    assert not d.get("fatal") and not d["errors"]
    camp = d["campaigns"][0]
    assert (camp["name"], camp["advertiser"]) == ("Campagne Test", "ANNONCEUR TEST")   # bloc au-dessus de l'en-tête (ligne 45)
    names = {p["name"]: p["site"] for p in camp["placements"]}
    assert names == {
        "R-Notoriete-CPM-Netflix-GrandPublic-SocioDemo-HF1834-PreRoll-1x1-Multidevice": "AmplifiProgrammatic",
        "R-Notoriete-CPM-TF1-Seniors-Custom-DataFoyerRetraite-PreRoll-0x0-Multidevice": "TF1 +",
        "R-Notoriete-dCPM-Meta-GrandPublic-SocioDemo-HF63-LinkAdVideo-1x1-Multidevice": "Facebook & Instagram",
        "R-Notoriete-dCPM-Meta-GrandPublic-LookAlike-VIEWERS-LinkAdVideo-1x1-Multidevice": "Facebook & Instagram",
    }
    creas = sorted({c["name"] for a in camp["ads"] for c in a["creatives"]})
    assert creas == ["P-LinkAdVideo-1x1-POVJEUNESA", "P-LinkAdVideo-1x1-POVJEUNESB",    # partagées par les 2 ciblages Meta
                     "P-PreRoll-1x1-POVJEUNESA", "P-PreRoll-1x1-POVJEUNESB", "V-PreRoll-0x0-CECIRETRAITESA"]
    assert any("Trafficking sheet d'agence" in l for l in d["ingest"])
    nomen = json.loads(d["nomenclature_auto"])                                      # gardée pour la réouverture
    assert nomen["defaults"]["placement"].startswith("{placement_type}-{objective}-{buy}-{partner}")
    rebuilt = json.loads(web_api.rebuild(json.dumps(d["table"])))                   # édition du tableau : mêmes noms
    assert {p["name"] for p in rebuilt["campaigns"][0]["placements"]} == set(names)


def test_targeting_detail_cleaning():
    assert agency_sheet.clean_detail("HF1834&Geoloc") == "HF1834"
    assert agency_sheet.clean_detail("60+CSP-&rural") == "60plusCSPminus"
    assert agency_sheet.clean_detail("HF63+&DentsuAudienceCSP-") == "HF63DentsuAudience"      # 25 car. max
    assert agency_sheet.clean_detail("PackAffinitaireFamilleEnfants&géoloc") == "PackAffFamilleEnfants"


def test_plain_plan_is_not_taken_for_an_agency_sheet():
    assert agency_sheet.read_convention(os.path.join(ROOT, "plan_media_template.csv")) is None
