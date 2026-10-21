# -*- coding: utf-8 -*-
"""Format « Campaign spreadsheet » de CM360 (Bulk Editor) : export du plan et
import comme source de plan.

Le fichier d'exemple fourni ne contenait que les 72 en-têtes (aucune valeur) :
les colonnes sont exactes, mais le **vocabulaire des valeurs** (types d'annonce
et de créative, compatibilités, structure de coût) est déduit de l'interface
CM360 et regroupé dans `VOCAB` pour être corrigé d'un seul endroit dès qu'un
export rempli est disponible.

Une ligne = une assignation placement + annonce + créative.
"""
import os
import re
import sys
from datetime import date, datetime
from typing import Dict, List, Optional

BULK_SHEET = "Campaign spreadsheet"

BULK_HEADERS = [
    'Site ID\n(Placement)',
    'Site name\n(Placement)',
    'Placement ID\n(Placement)',
    'Placement name\n(Placement)',
    'Group ID\n(Placement)',
    'Group type\n(Placement)',
    'Primary placement\n(Placement)',
    'Status\n(Placement)',
    'External ID\n(Placement)',
    'Compatibility\n(Placement)',
    'Payment source\n(Placement)',
    'Dimensions\n(Placement)',
    'Orientation\n(Placement)',
    'Duration\n(Placement)',
    'Content category\n(Placement)',
    'Strategy\n(Placement)',
    'Comments\n(Placement)',
    'Testing start date\n(Placement)',
    'Start date\n(Placement)',
    'End date\n(Placement)',
    'Cost structure\n(Placement)',
    'Cap costs\n(Placement)',
    'Units\n(Placement)',
    'Rate\n(Placement)',
    'Cost\n(Placement)',
    'Conversion window clicks\n(Placement)',
    'Conversion window impressions\n(Placement)',
    'Additional key-values\n(Placement)',
    'Opt out ad blocking\n(Placement)',
    'Publisher specification\n(Placement)',
    'Ad Serving Platform\n(Placement)',
    'Site Served\n(Placement)',
    'Conversion domain overrides\n(Placement)',
    'Conversion domains are manually overridden\n(Placement)',
    'Include in rotation\n(Placement assignment)',
    'Unassign\n(Placement assignment)',
    'Ad ID\n(Ad)',
    'Ad name\n(Ad)',
    'Type\n(Ad)',
    'Status\n(Ad)',
    'Comments\n(Ad)',
    'Start time\n(Ad)',
    'End time\n(Ad)',
    'Time zone ID',
    'Hard cut-off\n(Ad)',
    'Click tracker uses default landing page\n(Ad)',
    'Click tracker landing page ID\n(Ad)',
    'Click tracker landing page name\n(Ad)',
    'Click tracker click-through URL\n(Ad)',
    'Applied impression event tag IDs\n(Ad)',
    'Applied click event tag ID\n(Ad)',
    'Audience segment group name\n(Ad)',
    'Audience segment name\n(Ad)',
    'Priority\n(Ad)',
    'Impression ratio\n(Ad)',
    'Postal codes\n(Ad)',
    'Creative rotation type\n(Ad)',
    'Contextual keyword targeting\n(Ad)',
    'Creative ID\n(Creative)',
    'Creative name\n(Creative)',
    'Type\n(Creative)',
    'Creative compatibility\n(Creative)',
    'Start time\n(Creative assignment)',
    'End time\n(Creative assignment)',
    'Assignment event tags enabled\n(Creative assignment)',
    'Uses default landing page\n(Creative assignment)',
    'Landing page ID\n(Creative assignment)',
    'Landing page name\n(Creative assignment)',
    'Click-through URL\n(Creative assignment)',
    'Include in rotation\n(Creative assignment)',
    'Rotation value\n(Creative assignment)',
    'Unassign\n(Creative assignment)',
]

# Vocabulaire des valeurs (à valider avec un export rempli — voir l'en-tête).
VOCAB = {
    # type interne -> (valeur « Type (Creative) », valeur « Creative compatibility »)
    "creative": {
        "REDIRECT": ("Redirect", "Display"),
        "IMAGE": ("Image", "Display"),
        "VIDEO": ("In-stream video", "In-stream video"),
        "TRACKING": ("Tracking", "Display"),
    },
    "ad_type": {"standard": "Standard", "tracking": "Tracking"},
    "placement_compat": {"display": "Display", "video": "In-stream video", "tracking": "Display"},
    "cost_structure": {
        "PRICING_TYPE_CPM": "CPM", "PRICING_TYPE_CPC": "CPC",
        "PRICING_TYPE_CPA": "CPA", "PRICING_TYPE_FLAT_RATE": "Flat rate",
    },
    "ad_status": "Active",
    "rotation": "Random",
}

_COL = {h: i for i, h in enumerate(BULK_HEADERS)}


def _norm(h: str) -> str:
    from cm360_trafficker import normalize_header
    return normalize_header(h)


# Clés normalisées des colonnes utiles (ex. « Site ID\n(Placement) » -> site_id_placement)
K = {
    "site_id": "site_id_placement", "site_name": "site_name_placement",
    "placement": "placement_name_placement", "dims": "dimensions_placement",
    "start": "start_date_placement", "end": "end_date_placement",
    "cost_structure": "cost_structure_placement", "units": "units_placement",
    "cost": "cost_placement", "ad": "ad_name_ad", "ad_status": "status_ad",
    "ad_type": "type_ad", "ct_url_ad": "click_tracker_click_through_url_ad",
    "creative": "creative_name_creative", "ctype": "type_creative",
    "ct_url": "click_through_url_creative_assignment",
}


def is_bulk_header(normalized_headers) -> bool:
    """Vrai si l'en-tête est celui d'un export « Campaign spreadsheet » CM360."""
    hs = set(normalized_headers)
    return {K["placement"], K["ad"], K["creative"]} <= hs


# ---------------------------------------------------------------------------
# Import : Campaign spreadsheet -> lignes du plan canonique
# ---------------------------------------------------------------------------

def parse_bulk_date(v: str) -> str:
    """Date -> YYYY-MM-DD. Accepte ISO, JJ/MM/AAAA, AAAA/MM/JJ, avec ou sans heure."""
    s = (v or "").strip()
    if not s:
        return ""
    s = re.split(r"[ T]", s)[0]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return s   # laissé tel quel : la validation du plan le signalera


def _pricing(v: str) -> str:
    s = (v or "").lower()
    for key, out in (("cpm", "CPM"), ("cpc", "CPC"), ("cpa", "CPA"), ("flat", "FLAT")):
        if key in s:
            return out
    return ""


def _ctype(v: str) -> str:
    s = (v or "").lower()
    if "track" in s:
        return "TRACKING"
    if "video" in s or "instream" in s or "in-stream" in s:
        return "VIDEO"
    if "image" in s:
        return "IMAGE"
    if "redirect" in s or "third" in s:
        return "REDIRECT"
    return ""


def _num(v: str) -> Optional[float]:
    s = (v or "").strip().replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def bulk_to_plan_rows(rows: List[Dict[str, str]], campaign_name: str = "",
                      advertiser_name: str = "") -> List[Dict[str, str]]:
    """Convertit les lignes d'un Campaign spreadsheet (clés normalisées) en lignes
    du plan. Le fichier ne porte ni annonceur ni campagne : ils viennent des
    paramètres (--campaign-name / --advertiser-name). Dates de campagne = min des
    débuts / max des fins de placements. Objectif et budget = unités et coûts des
    placements CPM / tous placements (comptés une fois par placement).
    Les créatives non-tracking ont besoin d'un `snippet` ou d'un fichier, absents
    de ce format : la validation du plan le signale."""
    starts = [parse_bulk_date(r.get(K["start"], "")) for r in rows]
    ends = [parse_bulk_date(r.get(K["end"], "")) for r in rows]
    c_start = min((d for d in starts if d), default="")
    c_end = max((d for d in ends if d), default="")

    seen, units, budget = set(), 0.0, 0.0
    for r in rows:
        pl = r.get(K["placement"], "")
        if pl in seen:
            continue
        seen.add(pl)
        if _pricing(r.get(K["cost_structure"], "")) == "CPM":
            units += _num(r.get(K["units"], "")) or 0.0
        budget += _num(r.get(K["cost"], "")) or 0.0

    out = []
    first = True
    for r in rows:
        status = (r.get(K["ad_status"], "") or "").lower()
        out.append({
            "advertiser_name": advertiser_name,
            "campaign_name": campaign_name,
            "campaign_start": c_start,
            "campaign_end": c_end,
            "placement_name": r.get(K["placement"], ""),
            "site_id": r.get(K["site_id"], ""),
            "site_name": r.get(K["site_name"], ""),
            "size": re.sub(r"\s+", "", r.get(K["dims"], "")),
            "pricing_type": _pricing(r.get(K["cost_structure"], "")) or "CPM",
            "ad_name": r.get(K["ad"], ""),
            "creative_name": r.get(K["creative"], ""),
            "creative_type": _ctype(r.get(K["ctype"], "")),
            "snippet": "", "creative_path": "",
            "landing_page_url": r.get(K["ct_url"], "") or r.get(K["ct_url_ad"], ""),
            "active": "0" if status in ("inactive", "archived", "paused") else "1",
            "objective_impressions": (str(int(units)) if units and first else ""),
            "budget_eur": (f"{budget:g}" if budget and first else ""),
        })
        first = False
    return out


# ---------------------------------------------------------------------------
# Export : plan canonique -> Campaign spreadsheet (.xlsx pour le Bulk Editor)
# ---------------------------------------------------------------------------

def plan_to_bulk_rows(plan) -> List[List[str]]:
    """Une ligne par (emplacement, annonce, créative). `plan` = dict de
    CampaignSpec (voir cm360_trafficker)."""
    rows: List[List[str]] = []
    for camp in plan.values():
        for ad_name, ad in camp.ads.items():
            is_track = all(c.ctype == "TRACKING" for c in ad["creatives"])
            for pname in ad["placements"]:
                p = camp.placements[pname]
                for c in ad["creatives"]:
                    r = [""] * len(BULK_HEADERS)

                    def put(header: str, value) -> None:
                        r[_COL[header]] = "" if value is None else str(value)

                    ctype, ccompat = VOCAB["creative"][c.ctype]
                    put("Site ID\n(Placement)", p.site_id or "")
                    put("Site name\n(Placement)", p.site_name)
                    put("Placement name\n(Placement)", p.name)
                    put("Compatibility\n(Placement)", VOCAB["placement_compat"][
                        p.category or ("video" if c.ctype == "VIDEO" else "display")])
                    put("Dimensions\n(Placement)", f"{p.width}x{p.height}")
                    put("Start date\n(Placement)", camp.start)
                    put("End date\n(Placement)", camp.end)
                    put("Cost structure\n(Placement)",
                        VOCAB["cost_structure"].get(p.pricing_type, "CPM"))
                    put("Ad name\n(Ad)", ad_name)
                    put("Type\n(Ad)", VOCAB["ad_type"]["tracking" if is_track else "standard"])
                    put("Status\n(Ad)", VOCAB["ad_status"])
                    put("Creative rotation type\n(Ad)", VOCAB["rotation"])
                    put("Creative name\n(Creative)", c.name)
                    put("Type\n(Creative)", ctype)
                    put("Creative compatibility\n(Creative)", ccompat)
                    put("Click-through URL\n(Creative assignment)", c.landing_page_url)
                    rows.append(r)
    return rows


def write_bulk_xlsx(plan, path: str) -> int:
    """Écrit le Campaign spreadsheet (feuille « Campaign spreadsheet »).
    Renvoie le nombre de lignes de données."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font
    except ImportError:
        sys.exit("Export impossible : installez openpyxl (pip install openpyxl)")
    wb = Workbook()
    ws = wb.active
    ws.title = BULK_SHEET
    ws.append(BULK_HEADERS)
    for c in ws[1]:
        c.font = Font(bold=True)
        c.alignment = Alignment(wrap_text=True, vertical="top")
    data = plan_to_bulk_rows(plan)
    for r in data:
        ws.append(r)
    wb.save(path)
    return len(data)
