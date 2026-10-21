
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cm360_mcp_server.py
===================
Expose le moteur cm360_trafficker (et son reporting) en **serveur MCP**
(Model Context Protocol) : n'importe quelle IA — Vibe, ChatGPT, Claude,
Copilot, agent interne d'agence — peut alors piloter le trafficking et lire
les rapports en langage naturel.

C'est la pièce « couche adops côté agence » : les ad servers (Adform via son
MCP FLOW, Google Ad Manager/CM360 à venir) ouvrent leurs plateformes aux IA
des agences ; ce serveur leur fournit les outils métier : ingestion du plan,
nomenclatures, validation, push multi-plateformes, reporting réconcilié.

Outils exposés :
    analyze_plan     lit et valide un plan média (fichier ou Google Sheets),
                     applique les nomenclatures de nommage, renvoie l'aperçu
    traffic          exécute le trafficking complet (mock par défaut, ou
                     cm360 / adform avec identifiants), renvoie logs + rapport
    check_access     diagnostic d'accès à une plateforme
    report_delivery  rapports de diffusion + pacing / réconciliation au plan

Installation :
    pip install "mcp[cli]<2"

Connexion depuis un client MCP (stdio), par ex. configuration JSON :
    "mcpServers": {
      "cm360-trafficker": {
        "command": "python",
        "args": ["/chemin/vers/cm360_mcp_server.py"]
      }
    }

Exemples de requêtes en langage naturel une fois connecté :
    « Analyse plan_media.csv et applique nomenclatures.json »
    « Lance le trafficking en mode démo sur ce plan »
    « Comment se porte la campagne Printemps 2026 FR par rapport au plan ? »

Sécurité :
    - Par défaut, `traffic` exige platform="mock" ou des identifiants
      explicites : aucune écriture réelle par accident.
    - Les identifiants ne sont jamais journalisés.
"""

import json
import os

from mcp.server.fastmcp import FastMCP

from cm360_trafficker import (
    apply_nomenclature,
    build_adapter,
    load_nomenclature,
    load_rows_from_path,
    load_rows_from_source,
    plan_from_rows,
    resolve_plan_source,
    traffic_plan,
)
from cm360_reporting import (
    build_reporting_adapter,
    delivery_to_dict,
    report_for_plan,
)

mcp = FastMCP("cm360-trafficker")


def _load_plan(source: str, nomenclature_path: str = ""):
    """Charge + valide le plan (+ nomenclatures). Renvoie (plan, rows,
    renames, errors) et purge le fichier temporaire éventuel."""
    src = resolve_plan_source(source or "")
    try:
        rows = load_rows_from_path(src)
    finally:
        # RGPD : purge immédiate du fichier temporaire (export Google Sheet)
        if src != source:
            try:
                os.remove(src)
            except OSError:
                pass
    plan, errors = plan_from_rows(rows)
    renames = []
    naming = load_nomenclature(nomenclature_path) if nomenclature_path else {}
    if naming and not errors:
        plan, renames = apply_nomenclature(plan, naming)
    return plan, rows, renames, errors


def _plan_summary(plan, rows, renames, errors) -> str:
    lines = [f"{len(rows)} ligne(s) lue(s), {len(plan)} campagne(s), "
             f"{len(errors)} erreur(s)."]
    for r in renames:
        lines.append("[NOMENCLATURE] " + r)
    for camp in plan.values():
        lines.append(f"Campagne « {camp.name} » ({camp.start} -> {camp.end}) — "
                     f"annonceur : {camp.advertiser_id or camp.advertiser_name or '?'}")
        lines.append(f"  {len(camp.placements)} emplacement(s), "
                     f"{len(camp.ads)} annonce(s)")
        for ad_name, ad in camp.ads.items():
            lines.append(f"  Annonce « {ad_name} » : "
                         + ", ".join(c.name + " (" + c.ctype + ")"
                                     for c in ad["creatives"]))
    for e in errors:
        lines.append("[ERREUR] " + e)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Outils MCP
# ---------------------------------------------------------------------------

@mcp.tool()
def analyze_plan(source: str, nomenclature_path: str = "") -> str:
    """Analyse un plan média (chemin de fichier .csv/.xlsx ou URL d'un Google
    Sheet partagé en lecture) : validation ligne à ligne, campagnes détectées,
    et application des nomenclatures de nommage de l'annonceur (fichier JSON
    optionnel). Renvoie l'aperçu complet. Aucun envoi vers un ad server."""
    try:
        plan, rows, renames, errors = _load_plan(source, nomenclature_path)
    except SystemExit as e:
        return f"ERREUR : {e}"
    except Exception as e:
        return f"ERREUR : {e}"
    return _plan_summary(plan, rows, renames, errors)


@mcp.tool()
def traffic(source: str, platform: str = "mock",
            nomenclature_path: str = "", creatives_dir: str = "",
            service_account: str = "",
            profile_id: int = 0,
            adform_client_id: str = "", adform_client_secret: str = "",
            dry_run: bool = False) -> str:
    """Exécute le trafficking complet du plan vers un ad server :
    annonceur -> landing page -> campagne -> emplacements -> créatives ->
    annonces. Par défaut platform="mock" (simulation locale, aucune écriture
    réelle). Pour une exécution réelle, passer platform="cm360" (avec le
    chemin de la clé du compte de service Google) ou platform="adform" (avec
    les identifiants OAuth). dry_run=True valide seulement, sans appel API.
    Renvoie les logs d'exécution et le rapport JSON des objets créés."""
    try:
        plan, rows, renames, errors = _load_plan(source, nomenclature_path)
    except SystemExit as e:
        return f"ERREUR : {e}"
    except Exception as e:
        return f"ERREUR : {e}"
    if errors:
        return ("Plan invalide, trafficking NON exécuté :\n"
                + "\n".join("[ERREUR] " + e for e in errors))

    if dry_run:
        return ("[dry-run] Plan valide, aucun appel API effectué "
                f"(plateforme cible : {platform}).\n"
                + _plan_summary(plan, rows, renames, []))

    logs: list = []
    log = lambda m: logs.append(m)
    if renames:
        log(f"[NOMENCLATURE] {len(renames)} objet(s) renommé(s).")
    try:
        adapter = build_adapter(
            platform=platform, log=log,
            service_account=service_account,
            profile_id=profile_id or None,
            adform_client_id=adform_client_id,
            adform_client_secret=adform_client_secret,
            creatives_dir=creatives_dir)
        report = traffic_plan(adapter, plan, log=log)
    except SystemExit as e:
        return f"ERREUR : {e}\n" + "\n".join(logs)
    except Exception as e:
        return f"ERREUR : {e}\n" + "\n".join(logs)

    summary = (f"Terminé [{adapter.name}] : "
               f"{sum(len(v) for v in report['created'].values())} objet(s) créé(s), "
               f"{sum(len(v) for v in report['reused'].values())} réutilisé(s), "
               f"{len(report['errors'])} erreur(s).")
    return (summary + "\n\n--- Logs ---\n" + "\n".join(logs)
            + "\n\n--- Rapport (JSON) ---\n"
            + json.dumps(report, ensure_ascii=False, indent=2))


@mcp.tool()
def check_access(platform: str = "cm360", service_account: str = "",
                 profile_id: int = 0,
                 adform_client_id: str = "",
                 adform_client_secret: str = "") -> str:
    """Diagnostic d'accès à une plateforme (trafficking + reporting) sans rien
    modifier. platform="mock" pour vérifier la couche de simulation."""
    logs: list = []
    try:
        adapter = build_adapter(
            platform=platform, log=lambda m: logs.append(m),
            service_account=service_account, profile_id=profile_id or None,
            adform_client_id=adform_client_id,
            adform_client_secret=adform_client_secret)
        adapter.check_access()
    except SystemExit as e:
        return f"ERREUR : {e}\n" + "\n".join(logs)
    except Exception as e:
        return f"ERREUR : {e}\n" + "\n".join(logs)
    return "\n".join(logs) or "Accès OK."


@mcp.tool()
def report_delivery(source: str, platform: str = "mock",
                    service_account: str = "", profile_id: int = 0) -> str:
    """Rapport de diffusion des campagnes du plan média (impressions, clics,
    CTR par campagne) + pacing : comparaison aux objectifs de la colonne
    optionnelle `objective_impressions` du plan (statuts OK / EN RETARD /
    EN AVANCE). Par défaut platform="mock" (simulation) ; passer
    platform="cm360" avec la clé de compte de service pour un rapport réel."""
    try:
        plan, rows, renames, errors = _load_plan(source)
    except SystemExit as e:
        return f"ERREUR : {e}"
    except Exception as e:
        return f"ERREUR : {e}"
    if errors:
        return ("Plan invalide (le reporting utilise les dates de vol des "
                "campagnes) :\n" + "\n".join(errors))
    logs: list = []
    try:
        adapter = build_reporting_adapter(
            platform=platform, log=lambda m: logs.append(m),
            service_account=service_account, profile_id=profile_id or None)
        deliveries, flags = report_for_plan(rows, adapter)
    except SystemExit as e:
        return f"ERREUR : {e}\n" + "\n".join(logs)
    except Exception as e:
        return f"ERREUR : {e}\n" + "\n".join(logs)
    payload = delivery_to_dict(adapter.name, deliveries, flags)
    return (f"Rapport de diffusion [{adapter.name}] :\n"
            + "\n".join(flags)
            + "\n\n--- Données (JSON) ---\n"
            + json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    mcp.run(transport="stdio")

