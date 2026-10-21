# -*- coding: utf-8 -*-
"""Export du plan au format « bulk » Adform (classeur Campaigns / Orders / ...).

Le modèle `templates/adform_bulk_template.xlsx` est le classeur Adform (version 6)
dont les données d'exemple ont été retirées : structure, listes déroulantes et
feuilles de référence sont conservées (Adform exige de ne pas modifier la structure).

Ce que le classeur permet — et ce que le plan génère :
    Campaigns  : 1 ligne par campagne du plan   (nom, dates, budget, réglages)
    Orders     : 1 ligne par campagne           (commande portant le budget)
Les placements, annonces et créatives ne sont PAS exportés : la feuille
« Programmatic line items » est réservée au programmatique (sources d'inventaire
ou deals obligatoires) et « Banners » assigne des bannières existantes (IDs). Ils
resteront à créer dans Adform ou via l'API (adaptateur à compléter).

Valeurs par défaut reprises de l'exemple fourni : à adapter à chaque agence (ADFORM_DEFAULTS).
"""
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional

TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "templates", "adform_bulk_template.xlsx")

# Valeurs autorisées (listes déroulantes du classeur Adform v6)
CAMPAIGN_TYPES = ["Programmatic", "Non-programmatic", "Email", "Social media",
                  "Hybrid", "Search (Non-API)", "Print"]
ORDER_INPUT_MODES = ["Volume – Gross Price – Net Price"]   # autres modes : liste du classeur

ADFORM_DEFAULTS = {
    "currency": "EUR - Euro",
    "time_zone": "(UTC+01:00) Brussels, Copenhagen, Madrid, Paris",
    "campaign_type": "Non-programmatic",
    "input_mode": "Volume – Gross Price – Net Price",
    "id_fusion": "Off", "brand_safety": "Off", "avoid_uncategorized": "Off",
    "attribution_unit": "Per days", "attribution_days": 30,
    "tag_type": "Impressions",
    "conversion_attribution": "Attribute all post-interaction conversions",
    "attribution_rank": "Standard attribution rank",
}

# Colonne -> (feuille, texte attendu de l'en-tête). Garde-fou : si Adform change le
# modèle (autre version), l'export s'arrête au lieu de remplir de mauvaises colonnes.
CAMPAIGN_COLS = {
    "B": "*Name", "C": "Type", "D": "Currency", "G": "Start date", "H": "End date",
    "I": "Time zone", "K": "On/Off", "R": None, "T": "On/Off", "V": "Avoid uncategorized pages",
    "Z": "Per days/Per Hours", "AA": "Number", "AB": "Per days/Per Hours", "AC": "Number",
    "AN": "Tag Type", "AO": "Conversion attribution",
    "AP": "Standard attribution rank/Low attribution rank",
}
ORDER_COLS = {
    "C": "*Belongs to new campaign", "D": "*Name", "F": "Start date", "G": "End date",
    "AC": "Non-Programmatic budget", "AD": "Input mode",
}
HEADER_ROW = 3       # ligne des noms de colonnes
FIRST_DATA_ROW = 5   # première ligne de données


def _check_headers(ws, cols: Dict[str, str], sheet: str) -> None:
    for letter, expected in cols.items():
        if expected is None:
            continue
        got = str(ws[f"{letter}{HEADER_ROW}"].value or "").strip()
        if got != expected:
            raise ValueError(
                f"Modèle Adform inattendu (feuille {sheet}, colonne {letter} : "
                f"'{got}' au lieu de '{expected}'). Version du classeur différente de la v6 ?")


FORBIDDEN_NAME_CHARS = set("<>*'\"?|;\\")


def _check_name(name: str) -> None:
    """Règles Adform : 256 caractères max, sans < > * ' " ? | ; \\"""
    bad = sorted(set(name) & FORBIDDEN_NAME_CHARS)
    if bad or len(name) > 256:
        raise ValueError(f"Nom de campagne refusé par Adform ('{name[:40]}') : "
                         + (f"caractères interdits {''.join(bad)}" if bad else "plus de 256 caractères"))


def _date(s: str) -> Optional[datetime]:
    """Date absente du plan : case laissée vide (à compléter dans le classeur)."""
    return datetime.strptime(s, "%Y-%m-%d") if s else None


def write_adform_bulk(plan, path: str, campaign_type: str = "",
                      defaults: Dict = None) -> int:
    """Remplit les feuilles Campaigns et Orders à partir du plan. Renvoie le nombre
    de campagnes écrites."""
    try:
        from openpyxl import load_workbook
    except ImportError:
        sys.exit("Export impossible : installez openpyxl (pip install openpyxl)")
    d = dict(ADFORM_DEFAULTS, **(defaults or {}))
    ctype = campaign_type or d["campaign_type"]
    if ctype not in CAMPAIGN_TYPES:
        raise ValueError(f"Type de campagne Adform inconnu '{ctype}' ({', '.join(CAMPAIGN_TYPES)}).")
    wb = load_workbook(TEMPLATE)
    wc, wo = wb["Campaigns"], wb["Orders"]
    _check_headers(wc, CAMPAIGN_COLS, "Campaigns")
    _check_headers(wo, ORDER_COLS, "Orders")
    for camp in plan.values():
        _check_name(camp.name)
    for i, camp in enumerate(plan.values()):
        r = FIRST_DATA_ROW + i
        budget = getattr(camp, "budget_eur", None)
        c = {"B": camp.name, "C": ctype, "D": d["currency"],
             "G": _date(camp.start), "H": _date(camp.end), "I": d["time_zone"],
             "K": d["id_fusion"], "T": d["brand_safety"], "V": d["avoid_uncategorized"],
             "Z": d["attribution_unit"], "AA": d["attribution_days"],
             "AB": d["attribution_unit"], "AC": d["attribution_days"],
             "AN": d["tag_type"], "AO": d["conversion_attribution"],
             "AP": d["attribution_rank"]}
        if budget:
            c["R"] = budget
        for col, v in c.items():
            wc[f"{col}{r}"] = v
        o = {"C": camp.name, "D": camp.name, "F": _date(camp.start), "G": _date(camp.end),
             "AD": d["input_mode"]}
        if budget:
            o["AC"] = budget
        for col, v in o.items():
            wo[f"{col}{r}"] = v
    wb.properties.creator = "Trafficker"
    wb.properties.lastModifiedBy = "Trafficker"
    wb.save(path)
    return len(plan)
