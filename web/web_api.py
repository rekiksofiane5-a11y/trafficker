# -*- coding: utf-8 -*-
"""Pont entre la page web (JavaScript) et le moteur Trafficker, exécuté dans le
navigateur par Pyodide. Aucune donnée ne quitte le navigateur : pas de serveur,
pas d'appel réseau. Les fonctions renvoient du JSON (ou des octets pour les exports).
"""
import json
import os
import tempfile

from cm360_trafficker import (
    _ctype_label, apply_nomenclature, build_adapter, load_nomenclature,
    load_rows_from_path, naming_or_base, plan_from_rows, plan_gaps, traffic_plan,
)

# Plan analysé courant (une seule session : un onglet de navigateur)
_STATE: dict = {}


def _summary(plan) -> list:
    out = []
    for camp in plan.values():
        out.append({
            "name": camp.name, "advertiser": str(camp.advertiser_id or camp.advertiser_name or ""),
            "start": camp.start, "end": camp.end, "budget_eur": camp.budget_eur,
            "placements": [{"name": p.name, "size": f"{p.width}x{p.height}", "category": p.category,
                            "site": str(p.site_id or p.site_name or "")}
                           for p in camp.placements.values()],
            "ads": [{"name": n, "placements": ad["placements"],
                     "landing_page_url": ad.get("landing_page_url", ""),
                     "creatives": [{"name": c.name, "type": _ctype_label(c)} for c in ad["creatives"]]}
                    for n, ad in camp.ads.items()],
        })
    return out


def analyze(path: str, campaign_name: str = "", advertiser_name: str = "",
            nomenclature_json: str = "", creatives_dir: str = "") -> str:
    """Lit le plan déposé (CSV, XLSX, XLS, export CM360), le valide et applique
    les nomenclatures éventuelles. Le fichier est supprimé après lecture."""
    try:
        rows = load_rows_from_path(path, campaign_name, advertiser_name)
    except SystemExit as e:
        return json.dumps({"fatal": str(e)}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"fatal": f"Lecture impossible : {e}"}, ensure_ascii=False)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    plan, errors = plan_from_rows(rows, allow_incomplete=True)
    renames = []
    if not errors:
        naming = {}
        if nomenclature_json.strip():
            fd, tmp = tempfile.mkstemp(suffix=".json")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(nomenclature_json)
            try:
                naming = load_nomenclature(tmp)
            finally:
                os.remove(tmp)
        # Nomenclature de base (OBJECTIF-AUDIENCE-RÉGIE-CIBLAGE-FORMAT) si aucun fichier
        plan, renames = apply_nomenclature(plan, naming_or_base(naming), log=lambda m: None)
    from creative_specs import check_plan, spec_summary
    specs = check_plan(plan, creatives_dir) if not errors else []
    ctypes = sorted({c.ctype for camp in plan.values() for ad in camp.ads.values()
                     for c in ad["creatives"]})
    _STATE.clear()
    _STATE.update(plan=plan, rows=rows)
    return json.dumps({
        "rows": len(rows), "errors": errors, "renames": renames,
        "ingest": list(getattr(rows, "ingest_report", [])),
        "campaigns": _summary(plan),
        "specs": specs,
        "to_complete": plan_gaps(plan),
        "spec_refs": [s for s in (spec_summary(t) for t in ctypes) if s],
    }, ensure_ascii=False, default=str)


def _plan():
    if not _STATE.get("plan"):
        raise ValueError("Analysez d'abord un plan.")
    return _STATE["plan"]


def run_demo() -> str:
    """Trafficking simulé (adaptateur mock) : aucune écriture réelle."""
    logs: list = []
    report = traffic_plan(build_adapter("mock", log=logs.append), _plan(), log=logs.append)
    return json.dumps({"logs": logs,
                       "created": sum(len(v) for v in report["created"].values()),
                       "errors": report["errors"]}, ensure_ascii=False, default=str)


def delivery_demo() -> str:
    """Rapport de diffusion simulé + réconciliation (pacing impressions et dépense)."""
    from cm360_reporting import MockReportingAdapter, delivery_to_dict, report_for_plan
    if any(not c.start or not c.end for c in _plan().values()):
        raise ValueError("Dates de campagne à compléter avant le rapport de diffusion.")
    deliveries, flags = report_for_plan(_STATE["rows"] if _STATE.get("rows") else [],
                                        MockReportingAdapter(log=lambda m: None))
    return json.dumps(delivery_to_dict("mock", deliveries, flags), ensure_ascii=False)


def _export(writer, *args) -> bytes:
    fd, tmp = tempfile.mkstemp(suffix=".xlsx")
    os.close(fd)
    try:
        writer(_plan(), tmp, *args)
        with open(tmp, "rb") as f:
            return f.read()
    finally:
        os.remove(tmp)


def export_cm360() -> bytes:
    from cm360_bulk import write_bulk_xlsx
    return _export(write_bulk_xlsx)


def export_adform(campaign_type: str = "") -> bytes:
    from adform_bulk import write_adform_bulk
    return _export(write_adform_bulk, campaign_type)
