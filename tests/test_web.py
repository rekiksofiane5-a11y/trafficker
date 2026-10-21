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
        pg.wait_for_selector("text=Moteur prêt.", timeout=120000)
        yield pg
        browser.close()


def _analyze(page, path):
    page.set_input_files("#file", path)
    page.click("#analyze")
    page.wait_for_selector("#result:not(.hidden)", timeout=30000)
    page.wait_for_function("!document.getElementById('analyze').disabled", timeout=30000)


def test_template_plan_end_to_end(page):
    _analyze(page, os.path.join(ROOT, "plan_media_template.csv"))
    text = page.inner_text("#summary")
    assert "0 erreur(s)" in text and "Printemps_2026_FR" in text
    assert "TRACKING auto" in text and "VIDEO in-stream" in text
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
    _analyze(page, os.path.join(ROOT, "plan_media_template.csv"))
    with page.expect_download() as dl:
        page.click(btn)
    assert dl.value.suggested_filename == name
    out = tmp_path / name
    dl.value.save_as(out)
    assert sheet in openpyxl.load_workbook(out).sheetnames


def test_free_form_plan_and_errors(page, tmp_path):
    p = tmp_path / "libre.csv"
    p.write_text("Campagne,Emplacement,Format,Début,Fin,Annonce,Créatif,URL\n"
                 "C1,P1,300 x 250,02/11/2026,01/11/2026,A1,K1,https://x.fr\n", encoding="utf-8")
    _analyze(page, str(p))
    text = page.inner_text("#summary")
    assert "campaign_name ← colonne « Campagne »" in text
    assert "avant campaign_start" in text                     # fin avant début détectée
    assert page.is_disabled("#dl-cm360")                       # pas d'export d'un plan invalide


def test_nothing_sent_over_network(page, site):
    """Aucune requête vers un autre domaine que le site lui-même."""
    seen = []
    page.on("request", lambda r: seen.append(r.url))
    _analyze(page, os.path.join(ROOT, "plan_media_template.csv"))
    page.click("#demo")
    assert all(u.startswith(site) or u.startswith("blob:") or u.startswith("data:") for u in seen), seen
