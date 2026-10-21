"""Nomenclature de base : emplacement OBJECTIF-AUDIENCE-RÉGIE-CIBLAGE-FORMAT,
créative RÉGIE-FORMAT-MESSAGE (appliquée si aucun fichier de nomenclature)."""
import pytest

openpyxl = pytest.importorskip("openpyxl")
from cm360_trafficker import (BASE_NOMENCLATURE, apply_nomenclature, load_rows_from_path,
                              naming_or_base, plan_from_rows)


def _plan(tmp_path, rows):
    wb = openpyxl.Workbook()
    for r in rows:
        wb.active.append(r)
    p = tmp_path / "plan.xlsx"
    wb.save(p)
    plan, errors = plan_from_rows(load_rows_from_path(str(p)))
    assert errors == []
    return apply_nomenclature(plan, naming_or_base({}), log=None)


HEAD = ["Campagne", "Objectif", "Audience", "Régie", "Ciblage", "Format", "Message",
        "Début", "Fin", "URL"]


def test_base_nomenclature_names(tmp_path):
    plan, renames = _plan(tmp_path, [HEAD,
        ["Hiver", "Notoriété", "25-49 ans", "Le Monde", "Contextuel", "Pavé", "Soldes",
         "2026-11-02", "2026-12-15", "https://x.fr"],
        ["Hiver", "Trafic", "CSP+", "L'Équipe", "Retargeting", "Preroll", "Teaser 15s",
         "2026-11-02", "2026-12-15", "https://x.fr"],
    ])
    camp = next(iter(plan.values()))
    assert set(camp.placements) == {"NOTORIETE-25-49_ANS-LE_MONDE-CONTEXTUEL-PAVE",
                                    "TRAFIC-CSP+-L'EQUIPE-RETARGETING-PREROLL"}
    creas = {c.name for ad in camp.ads.values() for c in ad["creatives"]}
    assert creas == {"LE_MONDE-PAVE-SOLDES", "L'EQUIPE-PREROLL-TEASER_15S"}
    # annonce = nom de l'emplacement, références remappées
    for name, ad in camp.ads.items():
        assert ad["placements"] == [name] and name in camp.placements


def test_missing_segments_are_skipped(tmp_path):
    plan, _ = _plan(tmp_path, [["Campagne", "Objectif", "Régie", "Format", "Début", "Fin", "URL"],
        ["Hiver", "Conversion", "Leboncoin", "300x250", "2026-11-02", "2026-12-15", "https://x.fr"]])
    camp = next(iter(plan.values()))
    assert list(camp.placements) == ["CONVERSION-LEBONCOIN-300X250"]


def test_same_name_gets_a_suffix_instead_of_merging(tmp_path):
    plan, _ = _plan(tmp_path, [HEAD,
        ["Hiver", "Notoriété", "Tous", "Le Monde", "RON", "Pavé", "A", "2026-11-02", "2026-12-15", "https://x.fr"],
        ["Hiver", "Notoriété", "Tous", "Le Monde", "RON", "Pavé", "B", "2026-11-02", "2026-12-15", "https://x.fr"],
    ])
    camp = next(iter(plan.values()))
    # même emplacement, deux messages -> deux créatives distinctes en rotation
    assert list(camp.placements) == ["NOTORIETE-TOUS-LE_MONDE-RON-PAVE"]
    creas = sorted(c.name for ad in camp.ads.values() for c in ad["creatives"])
    assert creas == ["LE_MONDE-PAVE-A", "LE_MONDE-PAVE-B"]


def test_identical_lines_get_unique_names(tmp_path):
    plan, _ = _plan(tmp_path, [["Campagne", "Objectif", "Régie", "Emplacement", "Format", "Début", "Fin", "URL"],
        ["H", "Trafic", "Le Monde", "Home", "Pavé", "2026-11-02", "2026-12-15", "https://x.fr"],
        ["H", "Trafic", "Le Monde", "Article", "Pavé", "2026-11-02", "2026-12-15", "https://x.fr"]])
    camp = next(iter(plan.values()))
    assert set(camp.placements) == {"TRAFIC-LE_MONDE-PAVE", "TRAFIC-LE_MONDE-PAVE-2"}


def test_plan_without_nomenclature_data_keeps_original_names(tmp_path):
    plan, renames = _plan(tmp_path, [["Campagne", "Emplacement", "Format", "Début", "Fin", "URL"],
        ["Hiver", "Home", "300x250", "2026-11-02", "2026-12-15", "https://x.fr"]])
    assert renames == [] and "Home" in next(iter(plan.values())).placements


def test_client_file_overrides_base():
    assert naming_or_base({"defaults": {"placement": "{site_name}"}}) != BASE_NOMENCLATURE


def test_text_objective_vs_numeric_volume(tmp_path):
    wb = openpyxl.Workbook()
    for r in [["Campagne", "Emplacement", "Objectif", "Format", "Début", "Fin", "URL"],
              ["H", "Home", "500000", "300x250", "2026-11-02", "2026-12-15", "https://x.fr"]]:
        wb.active.append(r)
    p = tmp_path / "o.xlsx"
    wb.save(p)
    rows = load_rows_from_path(str(p))
    assert rows[0].get("objective_impressions") == "500000" and not rows[0].get("objective")
