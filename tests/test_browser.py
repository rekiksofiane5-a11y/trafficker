"""Parcours complet de l'UI dans un vrai navigateur (démo) : analyse ->
trafficking -> rapport de diffusion. Ignoré si Playwright/Chromium absents."""
import os
import socket
import threading
import time

import pytest

# En CI (TRAFFICKER_REQUIRE_BROWSER=1), un navigateur absent fait échouer au lieu d'ignorer.
REQUIRED = os.environ.get("TRAFFICKER_REQUIRE_BROWSER") == "1"
if REQUIRED:
    import playwright.sync_api as sync_api
else:
    sync_api = pytest.importorskip("playwright.sync_api")
pytest.importorskip("flask")
from werkzeug.serving import make_server

import cm360_trafficker_ui as ui

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Chromium : CHROMIUM_PATH si défini, sinon celui de l'environnement de dev, sinon
# celui installé par « playwright install » (cas de la CI).
CHROMIUM = os.environ.get("CHROMIUM_PATH", "/opt/pw-browsers/chromium")


@pytest.fixture(scope="module")
def server():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = make_server("127.0.0.1", port, ui.app)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()


def test_browser_demo_flow(server):
    with sync_api.sync_playwright() as p:
        kw = ({"executable_path": os.path.realpath(CHROMIUM)}
              if os.path.exists(CHROMIUM) else {})
        if hasattr(os, "geteuid") and os.geteuid() == 0:  # conteneurs : pas de sandbox en root
            kw["args"] = ["--no-sandbox", "--disable-gpu", "--no-zygote"]
        try:
            browser = p.chromium.launch(**kw)
        except Exception as e:  # pragma: no cover
            if REQUIRED:
                raise
            pytest.skip(f"Chromium indisponible : {e}")
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(server)
        page.click("#gear")
        page.click("label.ck")
        page.click("#attach")
        with page.expect_file_chooser() as fc:
            page.click("button:has-text(\"Plan média (.csv\")")
        fc.value.set_files(os.path.join(ROOT, "plan_media_template.csv"))
        page.click("#send")
        page.wait_for_selector("text=Lancer le trafficking", timeout=10000)
        page.click("#gear")  # referme les réglages pour ne pas masquer le chat
        page.click("button:has-text(\"Lancer le trafficking\")")
        page.wait_for_selector("text=Terminé.", timeout=15000)
        page.click("text=Rapport de diffusion")
        page.wait_for_selector("text=par emplacement", timeout=10000)
        assert "BN_Home_300x250" in page.inner_text("#chat")
        assert errors == []
        browser.close()
