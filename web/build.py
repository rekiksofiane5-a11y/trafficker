#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Construit le site 100 % navigateur dans web/dist :
page, moteur Python (exécuté par Pyodide), modèle Adform, wheels pures Python et
cœur Pyodide auto-hébergé (aucun CDN : le site fonctionne sans dépendance externe).
Prérequis : `npm ci` (fournit node_modules/pyodide). Lancé par `wrangler deploy`."""
import hashlib
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
DIST = os.path.join(WEB, "dist")

PY_MODULES = ["cm360_trafficker.py", "cm360_reporting.py", "cm360_bulk.py",
              "adform_bulk.py", "ingest.py", "plan_agent.py", "creative_specs.py", "reporting.py",
              "web/web_api.py"]
PYODIDE_FILES = ["pyodide.js", "pyodide.asm.js", "pyodide.asm.wasm",
                 "python_stdlib.zip", "pyodide-lock.json"]
EXAMPLES = ["plan_media_template.csv", "nomenclatures.json"]


def main() -> None:
    pyo = os.path.join(ROOT, "node_modules", "pyodide")
    if not os.path.isdir(pyo):
        sys.exit("node_modules/pyodide absent : lancez « npm ci » avant le build.")
    shutil.rmtree(DIST, ignore_errors=True)
    for d in ("py", "py/templates", "wheels", "pyodide", "exemples"):
        os.makedirs(os.path.join(DIST, d), exist_ok=True)
    shutil.copy(os.path.join(WEB, "index.html"), DIST)
    shutil.copy(os.path.join(WEB, "_headers"), DIST)
    shutil.copy(os.path.join(WEB, "engine.js"), DIST)
    shutil.copy(os.path.join(WEB, "demo_adserver.json"), DIST)
    shutil.copy(os.path.join(WEB, "cm_prompt.js"), DIST)
    shutil.copy(os.path.join(WEB, "pivot.js"), DIST)
    shutil.copy(os.path.join(WEB, "exemple_export_cm360.csv"), os.path.join(DIST, "exemples"))
    shutil.copy(os.path.join(WEB, "exemple_export_cm360_une_campagne.xlsx"), os.path.join(DIST, "exemples"))
    for m in PY_MODULES:
        shutil.copy(os.path.join(ROOT, m), os.path.join(DIST, "py"))
    shutil.copy(os.path.join(ROOT, "templates", "adform_bulk_template.xlsx"),
                os.path.join(DIST, "py", "templates"))
    os.makedirs(os.path.join(DIST, "py", "specs"), exist_ok=True)
    shutil.copy(os.path.join(ROOT, "specs", "cm360_creative_specs.json"),
                os.path.join(DIST, "py", "specs"))
    wheels = sorted(f for f in os.listdir(os.path.join(WEB, "wheels")) if f.endswith(".whl"))
    for w in wheels:
        shutil.copy(os.path.join(WEB, "wheels", w), os.path.join(DIST, "wheels"))
    for f in PYODIDE_FILES:
        shutil.copy(os.path.join(pyo, f), os.path.join(DIST, "pyodide"))
    for f in EXAMPLES:
        shutil.copy(os.path.join(ROOT, f), os.path.join(DIST, "exemples"))
    # Version = empreinte du moteur : affichée sur la page, et ajoutée aux URL pour
    # qu'aucun navigateur ne garde un ancien moteur en cache après un déploiement
    h = hashlib.sha1()
    for m in PY_MODULES:
        with open(os.path.join(ROOT, m), "rb") as f:
            h.update(f.read())
    manifest = {"version": h.hexdigest()[:8],
                "modules": [os.path.basename(m) for m in PY_MODULES],
                "templates": ["adform_bulk_template.xlsx"],
                "specs": ["cm360_creative_specs.json"], "wheels": wheels}
    with open(os.path.join(DIST, "py", "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f)
    size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(DIST) for f in fs)
    print(f"web/dist construit ({size / 1e6:.1f} Mo).")


if __name__ == "__main__":
    main()
