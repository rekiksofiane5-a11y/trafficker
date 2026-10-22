"""Version 100 % navigateur : le moteur Python tourne dans Chromium (Pyodide).
Parcours complet : chargement, analyse d'un plan, simulation, rapport, exports.
Ignoré si node_modules/pyodide ou Playwright manquent (sauf TRAFFICKER_REQUIRE_BROWSER=1)."""
import functools
import http.server
import io
import os
import subprocess
import sys
import threading

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "web", "dist")
REQUIRED = os.environ.get("TRAFFICKER_REQUIRE_BROWSER") == "1"
CHROMIUM = os.environ.get("CHROMIUM_PATH", "/opt/pw-browsers/chromium")

if not os.path.isdir(os.path.join(ROOT, "node_modules", "pyodide")) and not REQUIRED:
    pytest.skip("node_modules/pyodide absent (npm ci)", allow_module_level=True)
if REQUIRED:
    import playwright.sync_api as sync_api
else:
    sync_api = pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def site():
    if os.environ.get("TRAFFICKER_WEB_URL"):          # ex. wrangler dev (en-têtes réels)
        yield os.environ["TRAFFICKER_WEB_URL"]
        return
    subprocess.run([sys.executable, os.path.join(ROOT, "web", "build.py")], check=True)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=DIST)
    handler.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/"
    srv.shutdown()


@pytest.fixture(scope="module")
def page(site):
    with sync_api.sync_playwright() as p:
        kw = {"executable_path": os.path.realpath(CHROMIUM)} if os.path.exists(CHROMIUM) else {}
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            kw["args"] = ["--no-sandbox", "--disable-gpu", "--no-zygote"]
        browser = p.chromium.launch(**kw)
        pg = browser.new_page(accept_downloads=True)
        pg.errors = []
        pg.on("pageerror", lambda e: pg.errors.append(str(e)))
        pg.goto(site)
        pg.wait_for_selector("text=Moteur prêt", timeout=120000)
        _create_task(pg, "Tâche de test")
        yield pg
        browser.close()


def _create_task(page, name, **fields):
    page.click("#new-task")
    page.fill("#cd-name", name)
    for key, value in fields.items():
        page.fill("#cd-" + key, value)
    page.click("#cd-submit")
    page.wait_for_selector("#task-view:not([hidden])")


def _analyze(page, path, validate=True):
    if page.is_visible("#pm-reopen"):                     # zone de dépôt repliée après une production
        page.click("#pm-reopen")
    page.set_input_files("#file", path)
    page.click("#analyze")
    page.wait_for_selector("#result:not(.hidden)", timeout=30000)
    page.wait_for_function("!document.getElementById('analyze').disabled", timeout=30000)
    if validate and page.is_visible("#validate-step"):      # étape 1 validée : annonces et créas
        page.click("#validate-step")


def test_template_plan_end_to_end(page):
    _analyze(page, os.path.join(ROOT, "plan_media_template.csv"))
    text = page.text_content("#result")
    assert "0 erreur(s)" in text and "Printemps_2026_FR" in text
    assert "Aperçu dans CM360" in text
    assert "Tracking" in text and "In-stream video" in text and "Display" in text
    assert "Placement" in text and "nouveau" in text
    page.click("#demo")
    page.wait_for_selector("text=Trafficking simulé")
    assert "0 erreur(s)" in page.inner_text("#out")
    page.click("#delivery")
    page.wait_for_selector("text=Rapport de diffusion simulé")
    assert "BN_Home_300x250" in page.inner_text("#out") and "€" in page.inner_text("#out")
    assert page.errors == []


@pytest.mark.parametrize("btn,name,sheet", [("#dl-cm360", "campaign_spreadsheet_cm360.xlsx", "Campaign spreadsheet"),
                                            ("#dl-adform", "adform_bulk.xlsx", "Campaigns")])
def test_exports_download_valid_xlsx(page, tmp_path, btn, name, sheet):
    openpyxl = pytest.importorskip("openpyxl")
    page.select_option("#adserver", "adform" if "adform" in btn else "cm360")
    _analyze(page, os.path.join(ROOT, "plan_media_template.csv"))
    with page.expect_download() as dl:
        page.click(btn)
    page.select_option("#adserver", "cm360")
    assert dl.value.suggested_filename == name
    out = tmp_path / name
    dl.value.save_as(out)
    assert sheet in openpyxl.load_workbook(out).sheetnames


def test_free_form_plan_and_errors(page, tmp_path):
    p = tmp_path / "libre.csv"
    p.write_text("Campagne,Emplacement,Format,Début,Fin,Annonce,Créatif,URL\n"
                 "C1,P1,300 x 250,02/11/2026,01/11/2026,A1,K1,https://x.fr\n", encoding="utf-8")
    _analyze(page, str(p))
    text = page.text_content("#result")
    assert "campaign_name ← colonne « Campagne »" in text
    assert "à compléter" in text                               # fin avant début : vidée, à compléter
    assert not page.is_disabled("#dl-cm360")                   # ça avance : export possible


def test_nothing_sent_over_network(page, site):
    """Aucune requête vers un autre domaine que le site lui-même."""
    seen = []
    page.on("request", lambda r: seen.append(r.url))
    _analyze(page, os.path.join(ROOT, "plan_media_template.csv"))
    page.click("#demo")
    assert all(u.startswith(site) or u.startswith("blob:") or u.startswith("data:") for u in seen), seen


def test_creative_files_checked_against_cm360_specs(page, tmp_path):
    from test_creative_specs import html5_zip, png
    (tmp_path / "ban.png").write_bytes(png(600, 500))
    (tmp_path / "anim.zip").write_bytes(html5_zip("<html>pas de click</html>"))
    plan = tmp_path / "plan.csv"
    plan.write_text("campaign_name,campaign_start,campaign_end,placement_name,size,ad_name,"
                    "creative_name,creative_path,landing_page_url\n"
                    "C,2026-11-02,2026-12-15,P1,300x250,A1,K1,ban.png,https://x.fr\n"
                    "C,2026-11-02,2026-12-15,P2,300x250,A2,K2,anim.zip,https://x.fr\n", encoding="utf-8")
    page.set_input_files("#creas", [str(tmp_path / "ban.png"), str(tmp_path / "anim.zip")])
    _analyze(page, str(plan))
    text = page.text_content("#result")
    assert "Contrôle des créatives (specs CM360)" in text
    assert "ban.png : conforme" in text and "aucun click tag" in text
    assert "HTML5" in text
    assert page.is_disabled("#dl-cm360")              # créative hors specs : export bloqué
    page.set_input_files("#creas", [])


def test_yellow_cells_mode_in_browser(page, tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    from openpyxl.styles import PatternFill
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in [["Campagne", "Emplacement", "Format", "Début", "Fin", "URL"],
              ["Hiver", "Home", "300x250", "2026-11-02", "2026-12-15", "https://x.fr"],
              ["Hiver", "Article", "728x90", "2026-11-02", "2026-12-15", "https://x.fr"]]:
        ws.append(r)
    for c in range(1, 7):
        ws.cell(row=3, column=c).fill = PatternFill("solid", fgColor="FFFF00")
    wb.save(tmp_path / "jaune.xlsx")
    _analyze(page, str(tmp_path / "jaune.xlsx"))
    text = page.text_content("#result")
    assert "Mode cases jaunes" in text and "Article" in text
    assert "Home" not in page.inner_text("#preview-pane")


def test_page_stays_responsive_on_a_heavy_workbook(page, tmp_path):
    """Gros classeur (feuilles annexes, milliers de lignes) : l'analyse tourne dans le
    Web Worker, la page répond pendant ce temps."""
    import time
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Plan"
    ws.append(["Campagne", "Emplacement", "Format", "Début", "Fin", "URL"])
    for i in range(3000):
        ws.append(["Hiver", f"Emplacement {i}", "300x250", "2026-11-02", "2026-12-15", "https://x.fr"])
    annexe = wb.create_sheet("Référentiel")
    for i in range(8000):
        annexe.append([f"code {i}", i, "valeur"])
    wb.save(tmp_path / "lourd.xlsx")
    page.set_input_files("#file", str(tmp_path / "lourd.xlsx"))
    page.click("#analyze")
    t0 = time.time()
    assert page.evaluate("1 + 1") == 2                       # le fil principal répond
    assert time.time() - t0 < 2
    page.wait_for_function("!document.getElementById('analyze').disabled", timeout=120000)
    assert "3000 ligne(s)" in page.text_content("#result")


def test_missing_info_left_empty_and_listed(page, tmp_path):
    p = tmp_path / "incomplet.csv"
    p.write_text("Campagne,Emplacement,Format\nHiver,Home,Pavé\nHiver,Article,Méga-bannière\n", encoding="utf-8")
    _analyze(page, str(p))
    text = page.text_content("#result")
    assert "information(s) à compléter" in text                 # un seul rappel, pas de liste
    assert "Date de début — à compléter" not in text
    assert page.locator("#cf-campaign_start.cell-missing").count() == 1
    assert "erreur(s)" in text and "0 erreur(s)" in text
    assert not page.is_disabled("#dl-cm360")                     # export possible, cases vides
    page.click("#delivery")
    page.wait_for_selector("text=Dates de campagne à compléter")


def test_split_screen_edit_updates_preview(page, tmp_path):
    p = tmp_path / "edit.csv"
    p.write_text("Campagne,Régie,Emplacement,Format,Début,Fin,URL\n"
                 "Hiver,Le Monde,Home,Pavé,02/11/2026,15/12/2026,https://x.fr\n", encoding="utf-8")
    _analyze(page, str(p))
    assert page.is_visible("#editor table") and page.is_visible("#preview-pane .preview")
    assert "Home" in page.inner_text("#preview-pane")
    # l'objectif saisi dans le tableau entre dans la nomenclature de l'aperçu
    page.fill('#editor input[data-key="objective"]', "Notoriété")
    page.wait_for_function("document.getElementById('preview-pane').innerText.includes('NOTORIETE-LE_MONDE-PAVE')",
                           timeout=15000)
    # vider l'URL : case orange + « à compléter »
    page.fill('#editor input[data-key="landing_page_url"]', "")
    page.wait_for_selector("text=information(s) à compléter", timeout=15000)
    assert page.locator("#editor td.cell-missing").count() >= 1
    # ajouter une ligne : nouvel emplacement dans l'aperçu
    page.click("#add-row")
    page.fill('#editor tr[data-row="1"] input[data-key="placement_name"]', "Article")
    page.fill('#editor tr[data-row="1"] input[data-key="format_label"]', "Méga-bannière")
    page.wait_for_function("document.getElementById('preview-pane').innerText.includes('728 × 90')", timeout=15000)


def test_campaign_header_applies_to_all_rows(page, tmp_path):
    p = tmp_path / "entete.csv"
    p.write_text("Objectif,Régie,Emplacement,Format,URL\n"
                 "Notoriété,Le Monde,Home,Pavé,https://x.fr\n"
                 "Trafic,Le Monde,Article,Pavé,https://x.fr\n", encoding="utf-8")
    _analyze(page, str(p))
    assert page.is_visible("#cf-campaign_name")
    page.fill("#cf-campaign_name", "Printemps 2027")
    page.fill("#cf-campaign_start", "01/03/2027")
    page.fill("#cf-campaign_end", "31/03/2027")
    page.wait_for_function("document.getElementById('preview-pane').innerText.includes('Printemps 2027')", timeout=15000)
    pane = page.inner_text("#preview-pane")
    assert "01/03/2027" in pane and pane.count("Printemps 2027") == 1        # une seule campagne
    assert "PACKAGE-LE_MONDE-NOTORIETE" in pane and "PACKAGE-LE_MONDE-TRAFIC" in pane


def test_adform_preview_with_views(page, tmp_path):
    p = tmp_path / "adform.csv"
    p.write_text("Campagne,Objectif,Régie,Emplacement,Format,Début,Fin,Budget net,Volume (imp.),URL\n"
                 "SPF Fertilité,Notoriété,Amnet,Contextuel Santé,Audio,21/10/2026,22/11/2027,151619,11544211,https://x.fr\n"
                 "SPF Fertilité,Notoriété,Amnet,Comportemental,Audio,21/10/2026,22/11/2027,151619,11544211,https://x.fr\n",
                 encoding="utf-8")
    page.select_option("#adserver", "adform")
    _analyze(page, str(p))
    pane = page.inner_text("#preview-pane")
    assert "Aperçu dans Adform" in pane and "Direct Line Item" in pane and "Amnet" in pane
    assert "151\u202f619,00 €" in pane and "Imps" in pane and "21/10/2026" in pane
    assert page.is_visible("#dl-adform") and not page.is_visible("#dl-cm360")
    page.select_option("#adform-view", "banners")
    assert "Line item" in page.inner_text("#preview-pane")
    page.select_option("#adform-view", "tags")
    assert "Tag type" in page.inner_text("#preview-pane")
    page.select_option("#adserver", "cm360")                    # retour CM360 : arborescence
    assert "Aperçu dans CM360" in page.inner_text("#preview-pane")


def test_step_by_step_and_direct_edit_in_preview(page, tmp_path):
    p = tmp_path / "etapes.csv"
    p.write_text("Campagne,Objectif,Régie,Emplacement,Format,Message,Début,Fin,URL\n"
                 "Hiver,Notoriété,Le Monde,Home,Pavé,Soldes,02/11/2026,15/12/2026,https://x.fr\n"
                 "Hiver,Notoriété,Le Monde,Home,Pavé,Noël,02/11/2026,15/12/2026,https://x.fr\n"
                 "Hiver,Trafic,L'Équipe,Article,Méga-bannière,Soldes,02/11/2026,15/12/2026,https://x.fr\n",
                 encoding="utf-8")
    page.select_option("#adserver", "cm360")
    _analyze(page, str(p), validate=False)
    pane = lambda: page.inner_text("#preview-pane")
    # Étape 1 : emplacements sous la régie, pas encore d'annonces ni de créas
    assert "1. Emplacements" in pane() and "Placement" in pane() and "Tracking" not in pane()
    assert page.is_disabled("#dl-cm360")                               # export après validation
    # Grouper en package : la colonne Package du plan est remplie
    page.check('#preview-pane tr.pv-placement input[type=checkbox] >> nth=0')
    page.once("dialog", lambda d: d.accept("Package-Test"))
    page.click("#group-package")
    page.wait_for_function("document.getElementById('preview-pane').innerText.includes('Package-Test')", timeout=15000)
    assert page.locator('#editor input[data-key="package"]').first.input_value() == "Package-Test"
    # Renommer un emplacement par double-clic : reporté dans le plan (colonne imposée)
    page.locator("#preview-pane tr.pv-placement .pv-link").first.dblclick()
    page.fill("input.pv-rename", "MON-EMPLACEMENT")
    page.keyboard.press("Enter")
    page.wait_for_function("document.getElementById('preview-pane').innerText.includes('MON-EMPLACEMENT')", timeout=15000)
    assert page.locator('#editor input[data-key="placement_final"]').count() >= 1
    assert page.locator("#editor tr.hl").count() >= 1                  # lignes du plan surlignées
    # Glisser l'autre emplacement sur le site « Le Monde »
    src = page.locator("#preview-pane tr.pv-placement").nth(1)
    dst = page.locator("#preview-pane tr.pv-site", has_text="Le Monde")
    src.drag_to(dst)
    page.wait_for_function("document.querySelectorAll('#preview-pane tr.pv-site').length === 1", timeout=15000)
    # Étape 2 : annonces = emplacement × créative, nom par défaut « emplacement-créative »
    page.click("#validate-step")
    text = pane()
    assert "2. Annonces & créatives" in text and "MON-EMPLACEMENT-" in text
    assert not page.is_disabled("#dl-cm360")
    ad = page.locator("#preview-pane tr.pv-ad .pv-link").first
    ad.dblclick()
    page.fill("input.pv-rename", "ANNONCE-PERSO")
    page.keyboard.press("Enter")
    page.wait_for_function("document.getElementById('preview-pane').innerText.includes('ANNONCE-PERSO')", timeout=15000)
    assert page.locator('#editor input[data-key="ad_final"]').count() >= 1


def test_tasks_are_saved_restored_and_reporting_mode(page):
    """Coquille : tâche créée, production lancée, rechargement -> la tâche se rouvre telle quelle."""
    _create_task(page, "Lancement printemps", advertiser="Annonceur Démo", campaign="Printemps")
    page.fill("#instructions", "URL : https://www.exemple.fr")
    _analyze(page, os.path.join(ROOT, "plan_media_template.csv"))
    page.wait_for_function("document.getElementById('task-chips').textContent.includes('emplacements validés')")
    page.reload()
    page.wait_for_selector("text=Moteur prêt", timeout=120000)
    assert page.is_visible("#empty-view")
    page.click(".task-item:has-text('Lancement printemps')")
    page.wait_for_selector("#result:not(.hidden)")
    page.wait_for_selector("#back-step")                       # étape 2 restaurée
    assert page.input_value("#cf-campaign_name") == "Printemps"      # la pop-up fait foi
    assert page.input_value("#cf-advertiser_name") == "Annonceur Démo"
    assert page.input_value("#instructions") == "URL : https://www.exemple.fr"
    page.click(".scopes [data-scope=agency]")
    page.wait_for_selector("#task-list .task-item")
    page.click(".modes [data-mode=reporting]")
    assert page.is_visible("#empty-view")
    _create_task(page, "Bilan mi-parcours")
    assert page.is_visible("#rp-view") and not page.is_visible("#pm-step")
    page.click(".modes [data-mode=trafficking]")
    assert page.errors == []


def test_resizable_columns_and_folded_drop_zone(page, tmp_path):
    from fixtures.make_upsa import build
    path = tmp_path / "upsa.xlsx"
    build(str(path))
    _create_task(page, "UPSA Citrate")
    _analyze(page, str(path), validate=False)
    assert page.is_visible("#pm-compact") and not page.is_visible("#drop")      # dépôt replié
    assert "upsa.xlsx" in page.text_content("#pm-compact-text")
    th = page.locator("#editor th", has_text="Détail du ciblage")
    w0 = th.bounding_box()["width"]
    grip = th.locator(".col-grip")
    grip.scroll_into_view_if_needed()
    box = grip.bounding_box()
    page.mouse.move(box["x"] + 4, box["y"] + 5)
    page.mouse.down()
    page.mouse.move(box["x"] + 154, box["y"] + 5, steps=5)
    page.mouse.up()
    assert th.bounding_box()["width"] > w0 + 100                                # colonne agrandie
    assert "CONTEXTUEL" in page.text_content("#preview-pane")                # un package par ciblage
    page.click("#pm-reopen")
    assert page.is_visible("#drop")
    assert page.errors == []


def test_bulk_edit_modify_duplicate_delete(page, tmp_path):
    from fixtures.make_upsa import build
    path = tmp_path / "upsa.xlsx"
    build(str(path))
    _create_task(page, "UPSA bulk")
    _analyze(page, str(path), validate=False)
    rows = lambda: page.locator("#editor tbody tr").count()
    assert rows() == 16 and not page.is_visible("#bulk-bar")
    page.click('#editor tr[data-row="0"] td.sel input')
    page.click('#editor tr[data-row="3"] td.sel input', modifiers=["Shift"])         # plage 1 à 4
    assert page.text_content("#bulk-count") == "4 ligne(s) sélectionnée(s)"
    page.select_option("#bulk-key", "site_name")
    page.fill("#bulk-value", "DV360")
    page.click("#bulk-apply")
    page.wait_for_function("document.getElementById('preview-pane').innerText.includes('DV360')", timeout=15000)
    values = [page.input_value(f'#editor tr[data-row="{i}"] input[data-key="site_name"]') for i in range(5)]
    assert values == ["DV360"] * 4 + [""]
    page.click("#bulk-dup")
    assert rows() == 20 and page.text_content("#bulk-count") == "4 ligne(s) sélectionnée(s)"   # copies sélectionnées
    page.once("dialog", lambda d: d.accept())
    page.click("#bulk-delete")
    assert rows() == 16 and not page.is_visible("#bulk-bar")
    page.check("#ed-all")
    assert page.text_content("#bulk-count") == "16 ligne(s) sélectionnée(s)"
    page.click("#bulk-clear")
    assert not page.is_visible("#bulk-bar")
    assert page.errors == []


def test_reporting_check_and_scheduled_reports(page):
    """Reporting (démo, sans ad server connecté) : annonceur -> campagne -> check de mise en ligne
    (tableau de bord + Excel) puis report d'envoi par régie (carnet d'adresses, aperçu, programmation)."""
    openpyxl = pytest.importorskip("openpyxl")
    page.click(".modes [data-mode=reporting]")
    _create_task(page, "Check SUV")
    assert "démonstration" in page.text_content("#rp-source")
    page.fill("#rp-adv-q", "auto")
    page.click("#rp-adv-list button:has-text('Automobiles Démo')")
    page.click("#rp-camp-list button:has-text('Lancement SUV')")
    page.wait_for_selector("#rp-template:not([hidden])")
    assert "4 régie(s)" in page.text_content("#rp-selected")
    page.click(".tpl[data-tpl=check]")
    page.wait_for_selector(".kpis")
    dash = page.text_content("#rp-dash")
    assert "Régies avec données" in dash and "Aucune donnée" in dash and "Données reçues" in dash
    assert page.locator("#rp-check-table tbody tr").count() == 7
    with page.expect_download() as dl:
        page.click("#rp-dl-check")
    assert dl.value.suggested_filename == "check_mise_en_ligne_Lancement_SUV_electrique.xlsx"
    assert openpyxl.load_workbook(io.BytesIO(open(dl.value.path(), "rb").read())).sheetnames == ["Synthèse", "Par régie", "Emplacements", "Données jour"]
    page.click(".tpl[data-tpl=regies]")
    page.wait_for_selector(".rp-regie")
    options = page.locator(".rp-regie select option").all_text_contents()
    assert len(options) == 4 and all(any(n in o for n in ("Le Monde", "Les Échos", "Prisma", "Teads")) for o in options)
    page.click("#rp-launch")
    assert "Ajoutez au moins un e-mail" in page.text_content("#rp-send-msg")
    page.fill(".rp-regie input", "trafic@lemonde.fr")
    page.click("#rp-add-regie")
    assert page.locator(".rp-regie").count() == 2
    page.locator(".rp-regie").nth(1).locator("input").fill("pas-un-mail")
    page.click("#rp-launch")
    assert "E-mail invalide" in page.text_content("#rp-send-msg")
    page.locator(".rp-regie").nth(1).locator("input").fill("adops@regie.fr")
    page.locator(".rp-regie").nth(0).locator("button:has-text('Prévisualiser')").click()
    page.wait_for_selector("#rp-preview:not([hidden])")
    assert "Total" in page.text_content("#rp-preview") and "Impressions" in page.text_content("#rp-preview")
    page.click("#rp-launch")
    page.wait_for_selector("#rp-send-msg.ok")
    assert page.locator("#rp-scheduled tbody tr").count() == 2
    assert "trafic@lemonde.fr" in page.text_content(".rp-regie .sugg")                # carnet d'adresses
    page.click(".task-item:has-text('Check SUV')")                                   # réouverture
    page.wait_for_selector("#rp-template:not([hidden])")
    assert page.locator(".tpl.on").get_attribute("data-tpl") == "regies"
    page.click(".modes [data-mode=trafficking]")
    assert page.errors == []


def test_pacing_from_linked_plan_and_manage_scheduled_reports(page, tmp_path):
    """Check : rythme prévu (plan de la tâche de trafficking liée) vs livré ; reports programmés :
    pause, reprise, modification, suppression."""
    from fixtures.make_upsa import build
    path = tmp_path / "upsa.xlsx"
    build(str(path), 1600000, "8 000 €")
    _create_task(page, "UPSA Citrate — trafficking", advertiser="UPSA")
    page.fill("#instructions", "Régie : DV360 Open Market")       # noms finaux = ceux de la campagne (démo)
    _analyze(page, str(path), validate=False)
    page.wait_for_function("document.getElementById('task-chips').textContent.includes('produit')")
    page.click(".modes [data-mode=reporting]")
    _create_task(page, "UPSA check")
    page.click("#rp-adv-list button:has-text('UPSA')")
    page.click("#rp-camp-list button:has-text('Citrate')")
    page.click(".tpl[data-tpl=check]")
    page.wait_for_selector("#rp-pace-table")
    assert "UPSA Citrate — trafficking" in page.locator("#rp-plan option:checked").text_content()   # proposé seul
    dash = page.text_content("#rp-dash")
    assert "Rythme : livré / prévu à date" in dash and "Budget consommé (estimé)" in dash
    assert "16 emplacement(s) rapprochés du plan" in dash
    assert "sur 8 000 €" in dash.replace("\u202f", " ").replace("\xa0", " ")
    page.select_option("#rp-plan", "")
    page.wait_for_function("!document.getElementById('rp-pace-table')")
    page.click(".tpl[data-tpl=regies]")
    page.fill(".rp-regie input", "trafic@regie.fr")
    page.click("#rp-launch")
    page.wait_for_selector("#rp-sched-table")
    page.click("#rp-sched-table button:has-text('Pause')")
    assert "En pause" in page.text_content("#rp-sched-table") and "mis en pause" in page.text_content("#rp-send-msg")
    page.click("#rp-sched-table button:has-text('Reprendre')")
    assert "Actif" in page.text_content("#rp-sched-table")
    page.click("#rp-sched-table button:has-text('Modifier')")
    page.fill("#se-emails", "trafic@regie.fr, ops@regie.fr")
    page.select_option("#se-freq", "daily")
    page.click("#se-save")
    row = page.text_content("#rp-sched-table tbody tr")
    assert "ops@regie.fr" in row and "Quotidien" in row
    page.once("dialog", lambda d: d.accept())
    page.click("#rp-sched-table button:has-text('Supprimer')")
    assert not page.is_visible("#rp-sched-table") and "supprimé" in page.text_content("#rp-send-msg")
    page.click(".modes [data-mode=trafficking]")
    assert page.errors == []
