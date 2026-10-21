"""L'agent lit des plans médias réels « tels qu'ils arrivent » : en-tête décalé, bloc
d'infos, cellules fusionnées, totaux, colonnes mal nommées ou absentes, infos rangées
ailleurs, CSV à point-virgule en Windows-1252, plusieurs feuilles."""
import pytest

openpyxl = pytest.importorskip("openpyxl")
from cm360_trafficker import load_rows_from_path, plan_from_rows
import plan_agent


def _xlsx(path, sheets):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets:
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(r)
    wb.save(path)
    return str(path)


def _plan(path, **kw):
    rows = load_rows_from_path(path, **kw)
    plan, errors = plan_from_rows(rows)
    return rows, plan, errors, "\n".join(getattr(rows, "ingest_report", []))


def test_agency_plan_with_title_block_merged_cells_and_totals(tmp_path):
    p = _xlsx(tmp_path / "agence.xlsx", [
        ("Synthèse", [["Récapitulatif"], ["Budget global", "25 000 €"]]),
        ("Plan", [
            ["PLAN MÉDIA DIGITAL"],
            ["Annonceur : Client Démo"],
            ["Campagne", "Hiver 2026"],
            ["Période : du 02/11/2026 au 15/12/2026"],
            [],
            ["Support", "Emplacement", "Format", "Achat", "Volume (imp.)", "Budget net", "URL"],
            ["Le Monde", "Home", "300x250", "CPM", "500 000", "4 000 €", "https://client.fr/hiver"],
            [None, "Article", "728x90", "CPM", "250 000", "2 000 €", "https://client.fr/hiver"],
            ["L'Équipe", "Preroll", "640x360", "CPM", "100 000", "3 500 €", "https://client.fr/hiver"],
            ["TOTAL", None, None, None, "850 000", "9 500 €", None],
        ]),
    ])
    rows, plan, errors, report = _plan(p)
    assert errors == []
    camp = next(iter(plan.values()))
    assert (camp.name, camp.advertiser_name) == ("Hiver 2026", "Client Démo")
    assert (camp.start, camp.end) == ("2026-11-02", "2026-12-15")
    assert camp.budget_eur == 9500                       # somme des lignes, total ignoré
    assert len(rows) == 3
    assert rows[1]["site_name"] == "Le Monde"            # cellule fusionnée complétée
    assert "Feuille « Plan », en-tête ligne 6" in report
    assert "bloc d'en-tête" in report and "ignorée" in report


def test_semicolon_cp1252_english_headers_and_period_column(tmp_path):
    p = tmp_path / "plan.csv"
    p.write_bytes(("Line item;Creative size;Flight;Click URL;Cost model\n"
                   "Habillage été;970x250;02/11 - 15/12/2026;https://x.fr;CPM\n"
                   "Pavé;300x250;02/11 - 15/12/2026;https://x.fr;CPC\n").encode("cp1252"))
    rows, plan, errors, report = _plan(str(p), campaign_name="Été", advertiser_name="Démo")
    assert errors == []
    camp = next(iter(plan.values()))
    assert (camp.start, camp.end) == ("2026-11-02", "2026-12-15")
    assert "Habillage été" in camp.placements
    assert "période découpée" in report


def test_columns_found_by_content_when_headers_mean_nothing(tmp_path):
    p = _xlsx(tmp_path / "anonyme.xlsx", [("Feuil1", [
        ["Col A", "Col B", "Col C", "Col D", "Col E"],
        ["Bannière home", "300x250", "2026-11-02", "2026-12-15", "https://x.fr/a"],
        ["Bannière article", "728x90", "2026-11-02", "2026-12-15", "https://x.fr/b"],
        ["Pavé mobile", "320x50", "2026-11-03", "2026-12-14", "https://x.fr/c"],
    ])])
    rows, plan, errors, report = _plan(p, campaign_name="Test")
    assert errors == []
    camp = next(iter(plan.values()))
    assert set(camp.placements) == {"Bannière home", "Bannière article", "Pavé mobile"}
    assert camp.start == "2026-11-02" and camp.end == "2026-12-15"
    assert "contenu de la colonne « Col E »" in report        # URL reconnue au contenu
    assert "couvre du 2026-11-02 au 2026-12-15" in report     # dates propres à chaque ligne


def test_information_in_the_wrong_place(tmp_path):
    p = _xlsx(tmp_path / "desordre.xlsx", [("Plan", [
        ["Campagne", "Emplacement", "Début", "Fin", "Commentaire"],
        ["Noël", "Home_728x90 CPM", "01/12/2026", "24/12/2026", "lien : https://x.fr/noel"],
        ["Noël", "Pavé 300 x 250", "01/12/2026", "24/12/2026", "voir https://x.fr/noel"],
    ])])
    rows, plan, errors, report = _plan(p)
    assert errors == []
    assert [r["size"] for r in rows] == ["728x90", "300x250"]
    assert rows[0]["landing_page_url"] == "https://x.fr/noel"
    assert rows[0]["pricing_type"] == "CPM"
    assert "retrouvé dans le nom" in report and "autre cellule" in report
    assert "Noms générés" in report                          # annonce et créative absentes


def test_several_sizes_in_one_cell(tmp_path):
    p = _xlsx(tmp_path / "multi.xlsx", [("Plan", [
        ["Campagne", "Site", "Formats", "Date début", "Date fin", "URL"],
        ["Printemps", "Ouest-France", "300x250 / 728x90 / 160x600", "2027-03-01", "2027-03-31", "https://x.fr"],
    ])])
    rows, plan, errors, report = _plan(p)
    assert errors == []
    assert sorted(r["size"] for r in rows) == ["160x600", "300x250", "728x90"]
    assert len({r["placement_name"] for r in rows}) == 3


def test_missing_campaign_falls_back_to_file_name_flagged(tmp_path):
    p = _xlsx(tmp_path / "sans_campagne.xlsx", [("Plan", [
        ["Emplacement", "Format", "Début", "Fin", "URL"],
        ["Home", "300x250", "2026-11-02", "2026-12-15", "https://x.fr"],
    ])])
    rows, plan, errors, report = _plan(p)
    assert errors == [] and next(iter(plan.values())).name == "sans campagne"
    assert "à vérifier" in report


@pytest.mark.parametrize("raw,out", [
    ("du 02/11/2026 au 15/12/2026", ("2026-11-02", "2026-12-15")),
    ("02/11 - 15/12/2026", ("2026-11-02", "2026-12-15")),
    ("15/12 au 10/01/2027", ("2026-12-15", "2027-01-10")),
    ("2026-11-02 → 2026-12-15", ("2026-11-02", "2026-12-15")),
])
def test_parse_period(raw, out):
    assert plan_agent.parse_period(raw) == out


@pytest.mark.parametrize("raw,out", [("02/11/26", "2026-11-02"), ("46328", "2026-11-02"),
                                     ("2026-11-02 00:00:00", "2026-11-02"), ("pas une date", "")])
def test_parse_date(raw, out):
    assert plan_agent.parse_date(raw) == out


def test_format_names_and_missing_formats(tmp_path):
    p = _xlsx(tmp_path / "noms.xlsx", [("Plan", [
        ["Version 1.5"],
        [],
        ["Campagne", "Support", "Format", "Début", "Fin", "URL"],
        ["Hiver", "Le Monde", "Pavé", "2026-11-02", "2026-12-15", "https://x.fr"],
        ["Hiver", "Le Monde", "Méga-bannière", "2026-11-02", "2026-12-15", "https://x.fr"],
        ["Hiver", "L'Équipe", "Preroll 15s", "2026-11-02", "2026-12-15", "https://x.fr"],
        ["Hiver", "Leboncoin", "Habillage", "2026-11-02", "2026-12-15", "https://x.fr"],
        ["Hiver", "Marmiton", "", "2026-11-02", "2026-12-15", "https://x.fr"],
    ])])
    rows, plan, errors, report = _plan(p)
    assert errors == []
    assert [r["size"] for r in rows] == ["300x250", "728x90", "640x360", "1x1", "1x1"]
    cats = {p.name: p.category for p in next(iter(plan.values())).placements.values()}
    assert [cats[r["placement_name"]] for r in rows] == ["display", "display", "video", "tracking", "tracking"]
    assert "en-tête ligne 3" in report
    assert "format IAB converti" in report and "emplacement de tracking" in report


@pytest.mark.parametrize("name,size", [("Grand angle", "300x600"), ("MPU", "300x250"),
                                       ("Interstitiel mobile", "320x480"), ("Billboard", "970x250"),
                                       ("Skyscraper", "120x600"), ("Bannière mobile", "320x50"),
                                       ("Native", "")])
def test_size_from_name(name, size):
    assert plan_agent.size_from_name(name) == size


def test_explicit_iab_size_is_display_with_its_dimension(tmp_path):
    p = _xlsx(tmp_path / "iab.xlsx", [("Plan", [
        ["Campagne", "Emplacement", "Format", "Début", "Fin", "URL"],
        ["Hiver", "Home", "300x600", "2026-11-02", "2026-12-15", "https://x.fr"],
        ["Hiver", "Mobile", "320x50", "2026-11-02", "2026-12-15", "https://x.fr"],
    ])])
    rows, plan, errors, report = _plan(p)
    assert errors == []
    ps = next(iter(plan.values())).placements
    assert (ps["Home"].width, ps["Home"].height, ps["Home"].category) == (300, 600, "display")
    assert (ps["Mobile"].width, ps["Mobile"].height, ps["Mobile"].category) == (320, 50, "display")


def test_campaign_from_file_name_when_absent(tmp_path):
    p = _xlsx(tmp_path / "MIN._SANTE_Hiver_2026.xlsx", [("Feuil1", [
        ["Emplacement", "Format", "Début", "Fin", "URL"],
        ["Home", "300x250", "2026-11-02", "2026-12-15", "https://x.fr"],
    ])])
    rows, plan, errors, report = _plan(p)
    assert errors == []
    assert next(iter(plan.values())).name == "MIN. SANTE Hiver 2026"
    assert "nom du fichier" in report and "à vérifier" in report


def test_campaign_from_meaningful_sheet_name(tmp_path):
    p = _xlsx(tmp_path / "export.xlsx", [("Campagne Noël 2026", [
        ["Emplacement", "Format", "Début", "Fin", "URL"],
        ["Home", "300x250", "2026-12-01", "2026-12-24", "https://x.fr"],
    ])])
    rows, plan, errors, report = _plan(p)
    assert next(iter(plan.values())).name == "Campagne Noël 2026"


def test_typed_campaign_wins_over_file_name(tmp_path):
    p = _xlsx(tmp_path / "fichier.xlsx", [("Feuil1", [
        ["Emplacement", "Format", "Début", "Fin", "URL"],
        ["Home", "300x250", "2026-11-02", "2026-12-15", "https://x.fr"],
    ])])
    rows, plan, errors, report = _plan(p, campaign_name="Saisie")
    assert next(iter(plan.values())).name == "Saisie"


def test_repeated_errors_are_grouped():
    rows = [{"campaign_name": "", "placement_name": f"P{i}", "size": "300x250", "ad_name": "A",
             "creative_name": f"K{i}", "campaign_start": "2026-11-02", "campaign_end": "2026-12-15",
             "landing_page_url": "https://x.fr"} for i in range(5)]
    _, errors = plan_from_rows(rows)
    assert len(errors) == 1
    assert errors[0].startswith("Lignes 2 à 6 : campaign_name manquant") and "Campagne" in errors[0]


def _ctx(tmp_path, top, name="bloc.xlsx"):
    table = [["Emplacement", "Format", "URL"], ["Home", "Pavé", "https://x.fr"]]
    return _plan(_xlsx(tmp_path / name, [("Plan", top + [[]] + table)]))


def test_header_block_labels_on_the_left(tmp_path):
    rows, plan, errors, report = _ctx(tmp_path, [
        ["Client", "Ministère Démo"],
        ["Nom de campagne", "Hiver 2026"],
        ["Date de début", "02/11/2026"],
        ["Date de fin", "15/12/2026"],
        ["Objectif général", "Notoriété"],
    ])
    assert errors == []
    camp = next(iter(plan.values()))
    assert (camp.advertiser_name, camp.name, camp.start, camp.end) == \
        ("Ministère Démo", "Hiver 2026", "2026-11-02", "2026-12-15")
    assert rows[0]["objective"] == "Notoriété"                  # sert à la nomenclature


def test_header_block_labels_above_values(tmp_path):
    rows, plan, errors, report = _ctx(tmp_path, [
        ["Client", "Campaign name", "Date de début", "Date de fin", "Objectif général"],
        ["Démo SA", "Printemps 2027", "2027-03-01", "2027-03-31", "Trafic"],
    ])
    assert errors == []
    camp = next(iter(plan.values()))
    assert (camp.advertiser_name, camp.name, camp.start, camp.end) == \
        ("Démo SA", "Printemps 2027", "2027-03-01", "2027-03-31")
    assert rows[0]["objective"] == "Trafic"


def test_header_block_with_colons_and_nomenclature(tmp_path):
    from cm360_trafficker import apply_nomenclature, naming_or_base
    rows, plan, errors, report = _ctx(tmp_path, [
        ["Client :", "Démo"], ["Campagne :", "Été"], ["Début :", "01/06/2027"],
        ["Fin :", "30/06/2027"], ["Objectif général :", "Conversion"],
    ])
    assert errors == []
    plan, _ = apply_nomenclature(plan, naming_or_base({}), log=None)
    assert list(next(iter(plan.values())).placements) == ["CONVERSION-PAVE"]


def test_numeric_objective_in_header_block_is_a_volume(tmp_path):
    rows, plan, errors, report = _ctx(tmp_path, [
        ["Campagne", "X"], ["Début", "2027-01-01"], ["Fin", "2027-01-31"], ["Objectif", "2 000 000"]])
    assert not rows[0].get("objective")


def test_client_value_is_not_mistaken_for_a_label(tmp_path):
    rows, plan, errors, report = _ctx(tmp_path, [
        ["Annonceur", "Client Démo"], ["Campagne", "Hiver"], ["Début", "2026-11-02"], ["Fin", "2026-12-15"]])
    camp = next(iter(plan.values()))
    assert (camp.advertiser_name, camp.name) == ("Client Démo", "Hiver")
