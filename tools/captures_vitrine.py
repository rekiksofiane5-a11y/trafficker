#!/usr/bin/env python3
"""Captures de l'application pour le site vitrine (section « Du plan à la diffusion »).

Refait les quatre images de site/captures/ à partir de l'application réelle, en thème nuit,
avec des données 100 % fictives : un PM « Marque Démo » généré ici et les campagnes de démo,
dont les régies sont renommées (Régie Actu, Régie Vidéo…) pour ne montrer aucun vrai éditeur
avec de faux chiffres. À relancer après une évolution visible de l'interface :

    python3 web/build.py && python3 tools/captures_vitrine.py

Prérequis : Playwright + Chromium (CHROMIUM_PATH, défaut /opt/pw-browsers/chromium), Pillow.
"""
import csv
import datetime
import functools
import http.server
import io
import json
import os
import tempfile
import threading

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "web", "dist")
OUT = os.path.join(ROOT, "site", "captures")
CHROMIUM = os.environ.get("CHROMIUM_PATH", "/opt/pw-browsers/chromium")
WIDTH, HEIGHT, SHOT_H = 1200, 820, 600          # fenêtre du navigateur, hauteur d'une capture
OUT_W = 1400                                    # largeur des images publiées (WebP)

# Régies fictives à la place des éditeurs du jeu de démonstration
RENAME = {"Le Monde": "Régie Actu", "LE_MONDE": "REGIE_ACTU", "Les Échos": "Régie Éco", "LES_ECHOS": "REGIE_ECO",
          "Prisma Media": "Régie Magazines", "PRISMA": "MAGAZINES", "Teads": "Régie Vidéo", "TEADS": "VIDEO",
          "Le Figaro": "Régie Infos", "Leboncoin": "Régie Annonces", "DV360 Open Market": "DSP Open Market"}
FAKE_SITES = ["Régie Actu", "Régie Vidéo", "Régie Magazines", "Régie Éco"]
HIDE = "#help-btn, #status, .status-line { visibility: hidden !important; }"


def demo_json() -> bytes:
    with open(os.path.join(DIST, "app", "demo_adserver.json"), encoding="utf-8") as f:
        text = f.read()
    for a, b in RENAME.items():
        text = text.replace(a, b)
    d = json.loads(text)
    d["sites"] += [{"id": str(9100 + i), "name": n} for i, n in enumerate(FAKE_SITES)]
    return json.dumps(d, ensure_ascii=False).encode("utf-8")


def demo_plan(path: str) -> None:
    """PM fictif tel qu'une agence l'envoie : colonnes libres, ciblages, UTM, budgets."""
    d0 = datetime.date.today() + datetime.timedelta(days=10)
    d1 = d0 + datetime.timedelta(days=41)
    fr = lambda d: d.strftime("%d/%m/%Y")
    url = "https://www.marque-demo.fr/printemps?utm_source={}&utm_medium=display&utm_campaign=printemps"
    rows = [["Annonceur", "Campagne", "Objectif", "Régie", "Ciblage", "Emplacement", "Format", "Début", "Fin",
             "Budget net", "Volume (imp.)", "URL"]]
    lines = [("Régie Actu", "Contextuel", "Home page", "Pavé", 6000, 1500000),
             ("Régie Actu", "Contextuel", "Article", "Grand angle", 4500, 900000),
             ("Régie Actu", "Socio-démo", "Rotation générale", "Méga-bannière", 3000, 1000000),
             ("Régie Magazines", "Affinitaire", "Habillage", "Habillage", 8000, 600000),
             ("Régie Magazines", "Affinitaire", "Rotation", "Pavé", 2500, 700000),
             ("Régie Vidéo", "Comportemental", "In-read", "Vidéo in-read", 9000, 450000),
             ("Régie Vidéo", "Comportemental", "Outstream", "Vidéo outstream", 7000, 400000),
             ("Régie Éco", "Contextuel", "Rubrique Marchés", "Pavé", 3500, 500000)]
    for site, cib, empl, fmt, budget, vol in lines:
        src = site.lower().replace("régie ", "").replace("é", "e")
        link = url.format(src)
        if empl == "Rubrique Marchés":                 # défauts réalistes, relevés par les contrôles
            link = "https://www.marque-demo.fr/printemps"
        if empl == "Outstream":
            link = link.replace("https://", "http://")
        rows.append(["Marque Démo", "Lancement printemps", "Notoriété", site, cib, empl, fmt, fr(d0), fr(d1),
                     f"{budget} €", str(vol), link])
    with open(path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)


def save(png: bytes, name: str) -> None:
    img = Image.open(io.BytesIO(png)).convert("RGB")
    img = img.crop((0, 0, img.width, round(img.height * SHOT_H / HEIGHT)))      # haut de la fenêtre
    img = img.resize((OUT_W, round(img.height * OUT_W / img.width)), Image.LANCZOS)
    img.save(os.path.join(OUT, name), "WEBP", quality=82, method=6)
    print(f"  {name} : {os.path.getsize(os.path.join(OUT, name)) // 1024} Ko")


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    handler = functools.partial(Quiet, directory=DIST)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/app/"
    tmp = tempfile.mkdtemp()
    plan = os.path.join(tmp, "PM_Marque_Demo_printemps.csv")
    demo_plan(plan)
    body = demo_json()
    with sync_playwright() as p:
        kw = {"executable_path": os.path.realpath(CHROMIUM)} if os.path.exists(CHROMIUM) else {}
        kw["args"] = ["--no-sandbox", "--disable-gpu", "--no-zygote"]
        browser = p.chromium.launch(**kw)
        ctx = browser.new_context(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=2,
                                  reduced_motion="reduce")
        ctx.add_init_script("try { localStorage.setItem('agopis_theme', 'dark'); } catch (e) {}")
        ctx.route("**/demo_adserver.json", lambda r: r.fulfill(status=200, body=body, content_type="application/json"))
        pg = ctx.new_page()
        pg.goto(base)
        pg.wait_for_selector("text=Moteur prêt", timeout=120000)
        pg.add_style_tag(content=HIDE)
        pg.evaluate("window.urlChecks = () => []")        # disponibilité des URL : vérifiée par le serveur en ligne

        def to(sel: str, gap: int) -> None:
            """L'app défile dans #main (la barre du haut reste en place) : amène `sel` en haut de cette zone."""
            pg.evaluate("""([sel, gap]) => { const m = document.getElementById('main'), e = document.querySelector(sel);
              m.scrollTop += e.getBoundingClientRect().top - m.getBoundingClientRect().top - gap; }""", [sel, gap])

        # 01 — Entrée : le PM déposé tel quel, « Votre PM est prêt »
        pg.set_input_files("#hero-file", plan)
        pg.wait_for_selector("#file-chip:not([hidden])")
        pg.wait_for_function("!document.getElementById('analyze').disabled", timeout=120000)
        pg.click("#analyze")
        pg.wait_for_selector("#pm-compact:not([hidden])", timeout=60000)
        pg.wait_for_timeout(1200)
        to("#task-view", 0)
        save(pg.screenshot(), "01-entree.webp")

        # 02 — Préparation : plan classé et nommé, aperçu tel que dans CM360
        to(".result-grid", 16)
        pg.wait_for_timeout(500)
        save(pg.screenshot(), "02-preparation.webp")

        # 03 — Validation : points à vérifier et aperçu, avant tout envoi
        pg.add_style_tag(content=".result-main { display: none !important; } #main { padding-bottom: 900px !important; }")
        to(".checks", 16)
        pg.wait_for_timeout(500)
        save(pg.screenshot(), "03-validation.webp")

        # 04 — Suivi : check de mise en ligne d'une campagne de démonstration
        pg.click(".modes [data-mode=reporting]")
        pg.wait_for_function("document.querySelectorAll('#rp-home-adv option').length > 1")
        label = next(o for o in pg.locator("#rp-home-adv option").all_text_contents() if "Automobiles" in o)
        pg.select_option("#rp-home-adv", label=label)
        pg.click("#rp-home-go")
        pg.wait_for_selector("#rp-template:not([hidden])")
        pg.click(".tpl[data-tpl=check]")
        pg.wait_for_function("document.querySelectorAll('#rp-camp-sel option').length > 1")
        pg.select_option("#rp-camp-sel", index=1)
        pg.click("#rp-validate")
        pg.wait_for_selector(".kpis")
        pg.wait_for_timeout(800)
        to("#rp-check", 16)
        pg.wait_for_timeout(500)
        save(pg.screenshot(), "04-suivi.webp")
        browser.close()
    srv.shutdown()


if __name__ == "__main__":
    main()
