# -*- coding: utf-8 -*-
"""Pont entre la page web (JavaScript) et le moteur Umnia, exécuté dans le
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


def _fr(d: str, time: str = "") -> str:
    """AAAA-MM-JJ -> JJ/MM/AAAA (affichage CM360) ; vide si absente."""
    if not d:
        return ""
    y, m, j = d.split("-")
    return f"{j}/{m}/{y}" + (f" {time}" if time else "")


CREATIVE_TYPE = {"TRACKING": "Tracking", "IMAGE": "Image", "HTML5": "HTML5",
                 "VIDEO": "In-stream video", "AUDIO": "In-stream audio", "REDIRECT": "Display redirect"}
ASSET_TYPE = {"IMAGE": "Image", "HTML5": "HTML5", "VIDEO": "Video", "AUDIO": "Audio"}
COMPAT = {"display": "Display", "video": "In-stream video", "audio": "In-stream audio",
          "tracking": "Display"}


def split_ads(plan, rows: list) -> None:
    """1 annonce = 1 emplacement × 1 créative. Nom par défaut : « emplacement-créative »,
    remplaçable par un nom saisi (colonne ad_final, ou double-clic dans l'aperçu)."""
    from cm360_trafficker import _unique
    for camp in plan.values():
        new_ads, used = {}, set()
        for ad in camp.ads.values():
            for pn in ad["placements"]:
                p = camp.placements[pn]
                for c in ad["creatives"]:
                    shared = [i for i in c.rows if i in p.rows] or list(c.rows)
                    override = next((rows[i].get("ad_final") for i in shared
                                     if i < len(rows) and rows[i].get("ad_final")), "")
                    name = _unique(override or f"{pn}-{c.name}", used)
                    new_ads[name] = {"placements": [pn], "creatives": [c], "rows": shared,
                                     "landing_page_url": ad.get("landing_page_url", "")}
        camp.ads = new_ads


def preview(plan) -> list:
    """Arborescence telle qu'elle apparaîtra dans CM360 : Site > Package > Emplacement >
    Annonce > Créative, avec les colonnes de la plateforme. ID vide = objet à créer.
    Chaque ligne porte les lignes du plan concernées (rows) et le champ qu'un renommage
    modifie (edit), pour l'édition directe dans l'aperçu."""
    rows = []
    for camp in plan.values():
        all_rows = sorted({i for p in camp.placements.values() for i in p.rows})
        rows.append({"level": 0, "kind": "campaign", "name": camp.name, "start": _fr(camp.start),
                     "end": _fr(camp.end), "type": "Campagne", "rows": all_rows, "edit": "campaign_name"})
        ads_by_pl: dict = {}
        for an, ad in camp.ads.items():
            for pn in ad["placements"]:
                ads_by_pl.setdefault(pn, []).append((an, ad))
        sites: dict = {}
        for p in camp.placements.values():
            site = p.site_name or (str(p.site_id) if p.site_id else "")
            sites.setdefault(site, {}).setdefault(p.package, []).append(p)
        for site, packages in sites.items():
            site_rows = sorted({i for pls in packages.values() for p in pls for i in p.rows})
            rows.append({"level": 1, "kind": "site", "name": site or "Site à compléter",
                         "id": "", "type": "Site", "missing": not site, "rows": site_rows,
                         "edit": "site_name", "site": site})
            for package, pls in packages.items():
                base = 2
                if package:
                    rows.append({"level": 2, "kind": "package", "name": package,
                                 "start": _fr(camp.start), "end": _fr(camp.end), "type": "Package",
                                 "rows": sorted({i for p in pls for i in p.rows}), "edit": "package",
                                 "site": site, "package": package})
                    base = 3
                for p in pls:
                    rows.append({"level": base, "kind": "placement", "name": p.name,
                                 "start": _fr(camp.start), "end": _fr(camp.end), "type": "Placement",
                                 "compatibility": COMPAT.get(p.category, "Display"),
                                 "dimensions": f"{p.width} × {p.height}", "rows": list(p.rows),
                                 "edit": "placement_final", "site": site, "package": package})
                    for an, ad in ads_by_pl.get(p.name, []):
                        tracking = all(c.ctype == "TRACKING" for c in ad["creatives"])
                        ad_rows = ad.get("rows") or list(p.rows)
                        rows.append({"level": base + 1, "kind": "ad", "name": an,
                                     "start": _fr(camp.start, "00:00"), "end": _fr(camp.end, "23:59"),
                                     "type": "Tracking" if tracking else "Standard",
                                     "url": ad.get("landing_page_url", ""), "rows": ad_rows,
                                     "edit": "ad_final"})
                        for c in ad["creatives"]:
                            rows.append({"level": base + 2, "kind": "creative", "name": c.name,
                                         "start": _fr(camp.start, "00:00"), "end": _fr(camp.end, "23:59"),
                                         "type": CREATIVE_TYPE.get(c.ctype, c.ctype),
                                         "asset_type": ASSET_TYPE.get(c.ctype, ""),
                                         "dimensions": "" if c.ctype in ("TRACKING", "VIDEO", "AUDIO")
                                         else f"{p.width} × {p.height}",
                                         "rows": ad_rows, "edit": "creative_final"})
    return rows


# Colonnes du tableau modifiable (ordre, libellé) ; « toujours » = affichées même vides
# 1 plan média = 1 annonceur = 1 campagne : campagne, annonceur et dates se saisissent
# une fois (en-tête du volet), pas par ligne.
CAMPAIGN_FIELDS = ["campaign_name", "advertiser_name", "campaign_start", "campaign_end"]
TABLE_COLUMNS = [
    ("objective", "Objectif"), ("site_name", "Régie / site"), ("package", "Package"),
    ("audience", "Audience"), ("targeting", "Ciblage"), ("device", "Devices"),
    ("placement_name", "Emplacement"), ("format_label", "Format"), ("size", "Dimensions"),
    ("placement_category", "Catégorie"), ("pricing_type", "Achat"), ("ad_name", "Annonce"),
    ("creative_name", "Créative"), ("message", "Message"), ("creative_path", "Fichier créatif"),
    ("snippet", "Tag"), ("landing_page_url", "URL de destination"), ("budget_eur", "Budget €"),
    ("placement_final", "Nom emplacement (imposé)"), ("ad_final", "Nom annonce (imposé)"),
    ("creative_final", "Nom créa (imposé)"),
    ("objective_impressions", "Volume"),
]
ALWAYS = {"site_name", "objective", "audience", "targeting", "placement_name", "format_label", "size",
          "creative_name", "landing_page_url"}


def _normalize(rows: list) -> list:
    """Valeurs saisies dans le tableau -> format du plan (dates JJ/MM/AAAA, formats
    « Pavé », budgets « 4 000 € »)."""
    import ingest
    import plan_agent
    out = []
    for r in rows:
        r = {k: ("" if v is None else str(v).strip()) for k, v in r.items()}
        for f in ("campaign_start", "campaign_end"):
            if r.get(f):
                r[f] = plan_agent.parse_date(r[f]) or r[f]
        if not plan_agent.RE_SIZE.search(r.get("size", "")) and r.get("size", "") != "1x1":
            label = r.get("format_label") or r.get("size", "")
            r["size"] = plan_agent.size_from_name(label) or (r.get("size") or "")
            if label and not r["size"]:
                r["size"] = plan_agent.TRACKING_SIZE
        elif plan_agent.RE_SIZE.search(r.get("size", "")):
            m = plan_agent.RE_SIZE.search(r["size"])
            r["size"] = f"{m.group(1)}x{m.group(2)}"
        for f, fn in ingest.NORMALIZERS.items():
            if r.get(f) and f not in ("campaign_start", "campaign_end"):
                r[f] = fn(r[f])
        out.append(r)
    # Ligne ajoutée à la main : annonce et créative nommées comme le fait Umnia
    seen = {(r.get("ad_name"), r.get("creative_name")) for r in out}
    for r in out:
        if r.get("placement_name") and not r.get("ad_name"):
            r["ad_name"] = r["placement_name"]
        if r.get("ad_name") and not r.get("creative_name"):
            base = f"{r['ad_name']}_{r['message']}" if r.get("message") else f"{r['ad_name']}_crea"
            name, n = base, 2
            while (r["ad_name"], name) in seen:
                name, n = f"{base}_{n}", n + 1
            r["creative_name"] = name
            seen.add((r["ad_name"], name))
    return out


def _build(rows: list, nomenclature_json: str, creatives_dir: str, report: list) -> str:
    """Plan -> nomenclature -> contrôles -> aperçu. Partagé par l'analyse et l'édition."""
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
        split_ads(plan, rows)
    from creative_specs import check_plan, spec_summary
    specs = check_plan(plan, creatives_dir) if not errors else []
    ctypes = sorted({c.ctype for camp in plan.values() for ad in camp.ads.values()
                     for c in ad["creatives"]})
    _STATE.update(plan=plan, rows=rows, nomen=nomenclature_json, creatives_dir=creatives_dir)
    present = {k for r in rows for k, v in r.items() if v}
    first = rows[0] if rows else {}
    campaign = {f: first.get(f, "") for f in CAMPAIGN_FIELDS}
    columns = [{"key": k, "label": lbl} for k, lbl in TABLE_COLUMNS if k in ALWAYS or k in present]
    return json.dumps({
        "rows": len(rows), "errors": errors, "renames": renames, "ingest": report,
        "campaigns": _summary(plan), "specs": specs, "to_complete": plan_gaps(plan),
        "preview": preview(plan), "preview_adform": preview_adform(plan),
        "table": [dict(r) for r in rows], "columns": columns,
        "campaign": campaign,
        "spec_refs": [s for s in (spec_summary(t) for t in ctypes) if s],
    }, ensure_ascii=False, default=str)


def _num_fr(v: str, unit: str = "") -> str:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return ""
    s = f"{n:,.2f}" if unit == "€" else f"{n:,.0f}"
    s = s.replace(",", "\u202f").replace(".", ",")
    return f"{s} {unit}".strip()


ADFORM_BANNER_TYPE = {"TRACKING": "Tracking (1x1)", "IMAGE": "Image", "HTML5": "HTML5",
                      "VIDEO": "Vidéo (VAST)", "AUDIO": "Audio (VAST)", "REDIRECT": "Tag tiers"}


def preview_adform(plan) -> dict:
    """Aperçu tel qu'il apparaîtra dans Adform, en trois vues (comme le menu de la
    campagne) : campagne (line items directs), bannières, tags."""
    camp_rows, banners, tags = [], [], []
    for camp in plan.values():
        budget = camp.budget_eur
        camp_rows.append({"level": 0, "kind": "campaign", "name": camp.name, "media": "",
                          "type": "", "status": "Nouveau", "start": _fr(camp.start),
                          "end": _fr(camp.end), "budget": _num_fr(budget, "€") if budget else "",
                          "volume": ""})
        ads_by_pl: dict = {}
        for an, ad in camp.ads.items():
            for pn in ad["placements"]:
                ads_by_pl.setdefault(pn, []).append((an, ad))
        for p in camp.placements.values():
            media = p.site_name or (str(p.site_id) if p.site_id else "")
            camp_rows.append({"level": 1, "kind": "lineitem", "name": p.name, "sub": "Direct Line Item",
                              "rows": list(p.rows), "edit": "placement_final",
                              "media": media, "type": "Direct", "status": "Nouveau",
                              "start": _fr(camp.start), "end": _fr(camp.end),
                              "budget": _num_fr(p.budget, "€") if p.budget else "",
                              "volume": (_num_fr(p.volume) + " Imps") if p.volume else "",
                              "missing_media": not media})
            ads = ads_by_pl.get(p.name, [])
            n_banners = sum(len(ad["creatives"]) for _, ad in ads)
            tracking = all(c.ctype == "TRACKING" for _, ad in ads for c in ad["creatives"])
            tags.append({"name": p.name, "media": media, "size": f"{p.width}x{p.height}",
                         "tag_type": "Tracking (1x1)" if tracking else "Adform tag",
                         "banners": n_banners, "status": "Nouveau"})
            for an, ad in ads:
                for c in ad["creatives"]:
                    banners.append({"name": c.name, "type": ADFORM_BANNER_TYPE.get(c.ctype, c.ctype),
                                    "rows": ad.get("rows") or list(p.rows), "edit": "creative_final",
                                    "size": "" if c.ctype in ("VIDEO", "AUDIO") else f"{p.width}x{p.height}",
                                    "line_item": p.name, "click_url": ad.get("landing_page_url", ""),
                                    "status": "Nouveau"})
    return {"campaign": camp_rows, "banners": banners, "tags": tags}


INSTRUCTION_KEYS = [
    (r"campagne|campaign|nom de (la )?campagne", "campaign_name", "set"),
    (r"annonceur|client|advertiser", "advertiser_name", "set"),
    (r"(date de )?d[ée]but|start", "campaign_start", "date"),
    (r"(date de )?fin|end", "campaign_end", "date"),
    (r"p[ée]riode|dates", "period", "period"),
    (r"url|landing|destination|lien", "landing_page_url", "fill"),
    (r"r[ée]gie|support|site|m[ée]dia", "site_name", "fill"),
    (r"objectif", "objective", "fill"),
    (r"audience|cible", "audience", "fill"),
    (r"ciblage|targeting", "targeting", "fill"),
    (r"devices?", "device", "fill"),
    (r"package", "package", "fill"),
]


def apply_instructions(rows: list, text: str, report: list) -> None:
    """Instructions saisies avec la tâche, une par ligne « clé : valeur » (ex.
    « Campagne : Hiver 2026 », « Période : du 02/11 au 15/12/2026 », « URL : https://… »).
    campagne/annonceur/dates s'imposent à tout le plan ; les autres complètent les cases
    vides. Le reste est noté sans être interprété."""
    import re
    import plan_agent
    for raw in re.split(r"[\n;]+", text or ""):
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"^\s*([^:=]{2,40}?)\s*[:=]\s*(.+)$", line)
        hit = None
        if m:
            key = m.group(1).strip().lower()
            for pattern, field, how in INSTRUCTION_KEYS:
                if re.fullmatch(pattern, key, re.I):
                    hit = (field, how, m.group(2).strip())
                    break
        if not hit:
            report.append(f"Instruction notée, non interprétée : « {line} »")
            continue
        field, how, value = hit
        if how == "period":
            a, b = plan_agent.parse_period(value)
            if not (a and b):
                report.append(f"Instruction non comprise (période) : « {line} »")
                continue
            for r in rows:
                r["campaign_start"], r["campaign_end"] = a, b
        elif how == "date":
            d = plan_agent.parse_date(value)
            if not d:
                report.append(f"Instruction non comprise (date) : « {line} »")
                continue
            for r in rows:
                r[field] = d
        elif how == "set":
            for r in rows:
                r[field] = value
        else:
            for r in rows:
                if not r.get(field):
                    r[field] = value
        report.append(f"Instruction appliquée : « {line} »")


def analyze(path: str, campaign_name: str = "", advertiser_name: str = "",
            nomenclature_json: str = "", creatives_dir: str = "", instructions: str = "") -> str:
    """Lit le plan déposé (CSV, XLSX, XLS, export CM360), le classe, le valide et
    applique les nomenclatures. Le fichier est supprimé après lecture."""
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
    _STATE.clear()
    report = list(getattr(rows, "ingest_report", []))
    rows = [dict(r) for r in rows]
    apply_instructions(rows, instructions, report)
    _STATE["report"] = report
    return _build(rows, nomenclature_json, creatives_dir, report)


def rebuild(table_json: str) -> str:
    """Tableau modifié dans la page -> plan, nomenclature, contrôles et aperçu recalculés."""
    rows = _normalize(json.loads(table_json))
    return _build(rows, _STATE.get("nomen", ""), _STATE.get("creatives_dir", ""),
                  _STATE.get("report", []))


def restore(table_json: str, nomenclature_json: str = "") -> str:
    """Réouverture d'une tâche enregistrée : repart du tableau sauvegardé, sans l'état d'une autre tâche."""
    _STATE.clear()
    _STATE["nomen"] = nomenclature_json or ""
    return _build(_normalize(json.loads(table_json)), _STATE["nomen"], "", [])


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
