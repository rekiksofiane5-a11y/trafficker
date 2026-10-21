import json

import pytest

import ingest
from cm360_trafficker import load_rows_from_path, plan_from_rows

LIBRE = (
    "Campagne,Support,Emplacement,Format (px),Début,Fin,Achat,Budget HT,Annonce,Créatif,"
    "Fichier,URL de destination,Commentaire interne\n"
    'Printemps 2026,Le Monde,Home,300 x 250 px,02/11/2026,15/12/2026,Coût pour mille,"4 000,50 €",'
    "Ad_A,Crea_A,banner.png,https://x.fr,ok\n"
    "Printemps 2026,Le Monde,Preroll,640×360,02/11/2026,15/12/2026,CPM,,Ad_V,Crea_V,spot.mp4,https://x.fr,\n"
    "Printemps 2026,Le Monde,Home,300 x 250 px,02/11/2026,15/12/2026,CPM,,Ad_T,Crea_T,,https://x.fr,\n"
)


@pytest.fixture
def libre(tmp_path):
    p = tmp_path / "libre.csv"
    p.write_text(LIBRE, encoding="utf-8")
    return str(p)


def test_free_form_plan_is_ingested(libre):
    rows = load_rows_from_path(libre)
    plan, errors = plan_from_rows(rows)
    assert errors == []
    camp = next(iter(plan.values()))
    assert (camp.start, camp.end) == ("2026-11-02", "2026-12-15")
    assert camp.budget_eur == 4000.5
    assert camp.placements["Home"].width == 300
    types = {c.name: c.ctype for ad in camp.ads.values() for c in ad["creatives"]}
    assert types == {"Crea_A": "IMAGE", "Crea_V": "VIDEO", "Crea_T": "TRACKING"}
    report = "\n".join(rows.ingest_report)
    assert "campaign_name ← colonne « Campagne »" in report and "Commentaire interne" in report


def test_canonical_plan_is_untouched():
    rows = [{h: "x" for h in ingest.CANONICAL}]
    assert ingest.ingest_rows(rows) is rows


def test_missing_required_fields_are_reported():
    rows = ingest.ingest_rows([{"campagne": "C", "format": "300x250"}])
    assert any("introuvables" in line for line in rows.ingest_report)


def test_campaign_name_parameter_fills_gap():
    rows = ingest.ingest_rows([{"emplacement": "P", "annonce": "A"}], campaign_name="Camp")
    assert rows[0]["campaign_name"] == "Camp"


@pytest.mark.parametrize("raw,out", [("4 000,50 €", "4000.50"), ("1.234,5", "1234.5"),
                                     ("1,234.5", "1234.5"), ("12000", "12000")])
def test_norm_budget(raw, out):
    assert float(ingest.norm_budget(raw)) == float(out)


def test_llm_mapping_is_validated():
    # Le faux modèle propose un champ inconnu et un doublon : seuls les choix valides restent
    def fake(prompt):
        assert "Colonnes inconnues" in prompt
        return json.dumps({"lien_clic": "landing_page_url", "zz": "champ_inexistant",
                           "autre": "landing_page_url"})
    rows = ingest.ingest_rows(
        [{"campagne": "C", "lien_clic": "https://x.fr", "zz": "1", "autre": "y"}], llm_call=fake)
    assert rows[0]["landing_page_url"] == "https://x.fr"
    assert any("IA" in line for line in rows.ingest_report)


def test_llm_garbage_answer_is_ignored():
    rows = ingest.ingest_rows([{"campagne": "C", "lien_clic": "u"}], llm_call=lambda p: "pas du json")
    assert "landing_page_url" not in rows[0]
