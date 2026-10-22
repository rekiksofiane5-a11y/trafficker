"""Création de campagne CM360 (aide « Configurer une campagne ») : champs lus dans le plan,
fiche de création et contrôles avant l'import du Campaign spreadsheet."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "web")]

import web_api  # noqa: E402

PLAN = ("Annonceur;Banque Démo\nCampagne;Crédit automne\nCode de facturation;PO-2026-118\nID externe;BQ_AUT-26\n"
        "Publicité politique;Non\n\n"
        "Régie;Emplacement;Format;Début;Fin;URL\n"
        "Le Monde;Home;300x250;02/11/2030;30/11/2030;https://www.banque.fr/credit\n")


def _rows(tmp_path, text=PLAN):
    p = tmp_path / "plan.csv"
    p.write_text(text, encoding="utf-8")
    return json.loads(web_api.analyze(str(p), "", "", "", ""))


def test_campaign_fields_read_from_plan_header(tmp_path):
    d = _rows(tmp_path)
    c = d["campaign"]
    assert (c["billing_code"], c["external_id"], c["eu_political"]) == ("PO-2026-118", "BQ_AUT-26", "Non")
    sheet = dict(d["cm360_campaign"])
    assert sheet["Billing invoice code"] == "PO-2026-118" and sheet["External ID"] == "BQ_AUT-26"
    assert sheet["EU political ads"] == "This campaign doesn't contain EU political ads"
    assert sheet["Default landing page"] == "https://www.banque.fr/credit"            # 1re URL du plan
    keys = {i["key"] for i in d["cm360_issues"]}
    assert not keys & {"campaign_name", "campaign_dates", "landing_page", "billing_code", "external_id", "eu_political"}


def test_campaign_rules(tmp_path):
    d = _rows(tmp_path)
    t = d["table"]
    for r in t:
        r.update(external_id="ID avec espaces", billing_code="X" * 65, campaign_start="2020-01-01",
                 campaign_end="2020-02-01", eu_political="", landing_page_url="")
    d2 = json.loads(web_api.rebuild(json.dumps(t)))
    lv = {i["key"]: i["level"] for i in d2["cm360_issues"]}
    assert lv["external_id"] == "bloquant" and lv["billing_code"] == "bloquant" and lv["landing_page"] == "bloquant"
    assert lv["campaign_dates"] == "alerte" and lv["eu_political"] == "alerte"         # début passé ; déclaration UE
    for r in t:
        r.update(campaign_start="2031-02-01", campaign_end="2031-01-01")
    lv = {i["key"]: i["level"] for i in json.loads(web_api.rebuild(json.dumps(t)))["cm360_issues"]}
    assert lv["campaign_dates"] == "bloquant"                                            # fin avant début
