# -*- coding: utf-8 -*-
"""Templates de reporting Umnia (à partir des données de l'ad server).

Deux templates :
- **Check de mise en ligne** : toutes les régies et tous les emplacements de la campagne,
  avec ce qui remonte (ou pas) dans l'ad server ; petit tableau de bord et classeur Excel.
- **Report régie** : diffusion jour par jour des emplacements d'une régie, envoyé
  automatiquement à la régie selon un calendrier (aperçu et Excel identiques à l'envoi).

Données en entrée (JSON, mêmes formats pour CM360, Adform et la démo) :
- campagne : {id, name, advertiser, start, end}
- emplacements : [{id, name, site, site_id, size, start, end}]
- diffusion : [{date, placement_id, impressions, clicks}] (une ligne par jour et emplacement)
"""
import hashlib
import io
import os
import re
import unicodedata
from datetime import date, timedelta
from typing import Dict, List, Optional

LIVE, NO_DATA, NOT_STARTED = "Données reçues", "Aucune donnée", "Pas encore démarré"
LATE, ON_TRACK, AHEAD = "En retard", "Dans le rythme", "En avance"
PACE_LOW, PACE_HIGH = 90, 110          # % du prévu à date : en dessous = retard, au-dessus = sur-livraison


def _d(s: str) -> Optional[date]:
    try:
        return date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


def _ctr(imp: int, clk: int) -> float:
    return round(clk / imp * 100, 2) if imp else 0.0


def _seed(*parts) -> int:
    return int(hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


# --- Démo : diffusion simulée, déterministe ------------------------------------------------

def demo_delivery(campaign: Dict, placements: List[Dict], today: str) -> List[Dict]:
    """Diffusion fictive jour par jour : environ 1 emplacement sur 4 sans donnée et une régie
    entière muette quand la campagne en compte au moins trois (cas typique d'un check)."""
    end_day = _d(today) - timedelta(days=1)
    sites = sorted({p.get("site", "") for p in placements})
    silent_site = sites[_seed(campaign.get("id"), "site") % len(sites)] if len(sites) >= 3 else None
    out = []
    for p in placements:
        s = _seed(campaign.get("id"), p.get("id"))
        if p.get("site") == silent_site or s % 4 == 0:
            continue
        start = _d(p.get("start") or campaign.get("start"))
        end = min(_d(p.get("end") or campaign.get("end")) or end_day, end_day)
        if not start or start > end:
            continue
        base = 4000 + s % 40000
        day = start
        while day <= end:
            k = _seed(p.get("id"), day.isoformat())
            imp = int(base * (0.7 + (k % 60) / 100))
            out.append({"date": day.isoformat(), "placement_id": str(p.get("id")),
                        "impressions": imp, "clicks": int(imp * (0.0008 + (k % 30) / 10000))})
            day += timedelta(days=1)
    return out


# --- Rythme de diffusion : prévu au plan média vs livré ---------------------------------------

def _key(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", s)


def _num(v) -> float:
    try:
        return float(str(v).replace("\u202f", "").replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def match_targets(placements: List[Dict], targets: List[Dict]) -> Dict[str, Dict]:
    """Emplacement de l'ad server -> ligne prévue du plan : nom identique (casse, accents et
    séparateurs ignorés), sinon un nom contenu dans l'autre (même régie de préférence)."""
    by_key = {_key(t.get("name")): t for t in targets if t.get("name")}
    out, used = {}, set()
    for p in placements:
        t = by_key.get(_key(p.get("name")))
        if t:
            out[str(p.get("id"))] = t
            used.add(id(t))
    for p in placements:
        pid, k = str(p.get("id")), _key(p.get("name"))
        if pid in out or not k:
            continue
        cands = [t for t in targets if id(t) not in used and _key(t.get("name"))
                 and (_key(t.get("name")) in k or k in _key(t.get("name")))]
        cands.sort(key=lambda t: (_key(t.get("site")) != _key(p.get("site")), abs(len(_key(t.get("name"))) - len(k))))
        if cands:
            out[pid] = cands[0]
            used.add(id(cands[0]))
    return out


def _span(a: Optional[date], b: Optional[date]) -> int:
    return (b - a).days + 1 if a and b and b >= a else 0


def _pace(planned: float, budget: float, delivered: int, start: Optional[date], end: Optional[date],
          today: date) -> Dict:
    """Prévu à date (linéaire sur la période), rythme, projection de fin et budget consommé estimé.
    Les données s'arrêtent à la veille : le prévu à date aussi."""
    total = _span(start, end)
    elapsed = _span(start, min(end, today - timedelta(days=1))) if start and end else 0
    expected = planned * elapsed / total if total else 0.0
    pace = round(delivered / expected * 100, 1) if expected else None
    status = "" if pace is None else LATE if pace < PACE_LOW else AHEAD if pace > PACE_HIGH else ON_TRACK
    projection = delivered / elapsed * total if elapsed else 0.0
    return {"planned": int(round(planned)), "expected": int(round(expected)), "delivered": delivered,
            "pace": pace, "pace_status": status,
            "projection_pct": round(projection / planned * 100, 1) if planned and elapsed else None,
            "budget": round(budget, 2), "spent": round(budget * delivered / planned, 2) if planned and budget else 0.0,
            "elapsed_days": elapsed, "total_days": total}


def pacing(campaign: Dict, placements: List[Dict], rows: List[Dict], targets: Optional[Dict], today: str) -> Dict:
    """Rythme par emplacement, par régie et pour la campagne, à partir du plan média lié."""
    if not targets:
        return {"available": False}
    now = _d(today)
    plan_pl = targets.get("placements") or []
    matched = match_targets(placements, plan_pl)
    c_start, c_end = _d(campaign.get("start")), _d(campaign.get("end"))
    per_pl, sites, tot = {}, {}, {"planned": 0.0, "budget": 0.0, "delivered": 0, "expected": 0.0}
    for r in rows:
        t = matched.get(r["id"])
        planned, budget = (_num(t.get("impressions")), _num(t.get("budget"))) if t else (0.0, 0.0)
        if not t or not (planned or budget):
            continue
        # Dates de diffusion : celles de l'ad server (emplacement puis campagne), sinon celles du plan
        start = _d(r.get("start")) or c_start or _d(t.get("start"))
        end = _d(r.get("end")) or c_end or _d(t.get("end"))
        pc = _pace(planned, budget, r["impressions"], start, end, now)
        pc["plan_name"] = t.get("name", "")
        per_pl[r["id"]] = pc
        s = sites.setdefault(r["site"], {"site": r["site"], "planned": 0.0, "expected": 0.0, "delivered": 0,
                                         "budget": 0.0, "spent": 0.0})
        for k in ("planned", "expected", "delivered", "budget", "spent"):
            s[k] += pc[k]
    for s in sites.values():
        s["pace"] = round(s["delivered"] / s["expected"] * 100, 1) if s["expected"] else None
        s["pace_status"] = "" if s["pace"] is None else LATE if s["pace"] < PACE_LOW else AHEAD if s["pace"] > PACE_HIGH else ON_TRACK
        s["planned"], s["expected"] = int(round(s["planned"])), int(round(s["expected"]))
        s["budget"], s["spent"] = round(s["budget"], 2), round(s["spent"], 2)
    if per_pl:
        tot = {k: sum(p[k] for p in per_pl.values()) for k in ("planned", "expected", "delivered", "budget", "spent")}
        elapsed = max(p["elapsed_days"] for p in per_pl.values())
        total_days = max(p["total_days"] for p in per_pl.values())
        pace = round(tot["delivered"] / tot["expected"] * 100, 1) if tot["expected"] else None
        kp = {**tot, "pace": pace, "pace_status": "" if pace is None else LATE if pace < PACE_LOW else AHEAD if pace > PACE_HIGH else ON_TRACK,
              "projection_pct": round(sum(p["delivered"] / p["elapsed_days"] * p["total_days"] for p in per_pl.values()
                                          if p["elapsed_days"]) / tot["planned"] * 100, 1) if tot["planned"] and elapsed else None,
              "level": "emplacements", "elapsed_days": elapsed, "total_days": total_days}
    else:
        # Pas d'objectif par ligne : objectif global de la campagne (volume et budget du plan)
        camp_t = targets.get("campaign") or {}
        planned, budget = _num(camp_t.get("impressions")), _num(camp_t.get("budget"))
        if not (planned or budget):
            return {"available": False, "reason": "Le plan média lié ne donne ni volume ni budget.",
                    "source": targets.get("source", "")}
        kp = _pace(planned, budget, sum(r["impressions"] for r in rows),
                   c_start or _d(camp_t.get("start")), c_end or _d(camp_t.get("end")), now)
        kp["level"] = "campagne"
    for k in ("planned", "expected"):
        kp[k] = int(round(kp[k]))
    kp["budget"], kp["spent"] = round(kp["budget"], 2), round(kp["spent"], 2)
    names = {_key(t.get("name")) for t in matched.values()}
    return {"available": True, "source": targets.get("source", ""), "kpis": kp, "placements": per_pl,
            "sites": sorted(sites.values(), key=lambda s: -s["planned"]),
            "matched": len(matched), "unmatched_plan": [t.get("name") for t in plan_pl if _key(t.get("name")) not in names]}


# --- Check de mise en ligne -----------------------------------------------------------------

def check(campaign: Dict, placements: List[Dict], delivery: List[Dict], today: str,
          targets: Optional[Dict] = None) -> Dict:
    """Synthèse : par emplacement (statut, volumes, 1re / dernière impression) et par régie ;
    avec le plan média lié (targets), rythme de diffusion prévu vs livré et budget."""
    now = _d(today)
    if targets and campaign.get("from_file"):
        placements = with_plan_placements(placements, targets)
    by_pl: Dict[str, Dict] = {}
    days = set()
    for r in delivery:
        if not (r.get("impressions") or r.get("clicks")):
            continue
        a = by_pl.setdefault(str(r["placement_id"]), {"impressions": 0, "clicks": 0, "first": "", "last": ""})
        a["impressions"] += int(r.get("impressions") or 0)
        a["clicks"] += int(r.get("clicks") or 0)
        d = r.get("date", "")
        if d:
            days.add(d)
            a["first"] = min(a["first"] or d, d)
            a["last"] = max(a["last"], d)
    rows = []
    for p in placements:
        a = by_pl.get(str(p.get("id")), {})
        start = _d(p.get("start") or campaign.get("start"))
        if a.get("impressions") or a.get("clicks"):          # clics seuls : click tracker 1x1
            status = LIVE
        elif start and now and start >= now:
            status = NOT_STARTED
        else:
            status = NO_DATA
        imp, clk = a.get("impressions", 0), a.get("clicks", 0)
        rows.append({"site": p.get("site") or "Régie inconnue", "id": str(p.get("id", "")), "name": p.get("name", ""),
                     "size": p.get("size", ""), "start": p.get("start") or campaign.get("start", ""),
                     "end": p.get("end") or campaign.get("end", ""), "impressions": imp, "clicks": clk,
                     "ctr": _ctr(imp, clk), "first": a.get("first", ""), "last": a.get("last", ""), "status": status})
    rows.sort(key=lambda r: (r["site"].lower(), r["name"].lower()))
    sites: Dict[str, Dict] = {}
    for r in rows:
        s = sites.setdefault(r["site"], {"site": r["site"], "placements": 0, "live": 0, "waiting": 0,
                                         "impressions": 0, "clicks": 0})
        s["placements"] += 1
        s["live"] += r["status"] == LIVE
        s["waiting"] += r["status"] == NOT_STARTED
        s["impressions"] += r["impressions"]
        s["clicks"] += r["clicks"]
    for s in sites.values():
        s["ctr"] = _ctr(s["impressions"], s["clicks"])
        expected = s["placements"] - s["waiting"]
        s["status"] = (NOT_STARTED if not expected else LIVE if s["live"] == expected
                       else NO_DATA if not s["live"] else "Partiel")
    imp = sum(r["impressions"] for r in rows)
    clk = sum(r["clicks"] for r in rows)
    site_list = sorted(sites.values(), key=lambda s: -s["impressions"])
    pace = pacing(campaign, placements, rows, targets, today)
    for r in rows:
        r["pacing"] = pace.get("placements", {}).get(r["id"])
    for s in site_list:
        s["pacing"] = next((x for x in pace.get("sites", []) if x["site"] == s["site"]), None)
    return {"campaign": campaign, "today": today, "pacing": pace,
            "kpis": {"impressions": imp, "clicks": clk, "ctr": _ctr(imp, clk),
                     "placements": len(rows), "placements_live": sum(r["status"] == LIVE for r in rows),
                     "sites": len(site_list), "sites_live": sum(s["live"] > 0 for s in site_list),
                     "days": len(days), "first": min(days) if days else "", "last": max(days) if days else ""},
            "sites": site_list, "placements": rows}


# --- Report régie -------------------------------------------------------------------------

REGIE_COLUMNS = ["Date", "Emplacement", "ID emplacement", "Format", "Impressions", "Clics", "CTR (%)"]


def regie_report(campaign: Dict, placements: List[Dict], delivery: List[Dict], site: str) -> Dict:
    """Diffusion jour par jour des emplacements d'une régie : contenu exact du fichier envoyé."""
    pls = {str(p.get("id")): p for p in placements if (p.get("site") or "") == site}
    rows = []
    for r in sorted(delivery, key=lambda r: (r.get("date", ""), str(r.get("placement_id")))):
        p = pls.get(str(r.get("placement_id")))
        if not p:
            continue
        imp, clk = int(r.get("impressions") or 0), int(r.get("clicks") or 0)
        rows.append([r.get("date", ""), p.get("name", ""), str(p.get("id", "")), p.get("size", ""),
                     imp, clk, _ctr(imp, clk)])
    imp = sum(r[4] for r in rows)
    clk = sum(r[5] for r in rows)
    return {"site": site, "campaign": campaign, "columns": REGIE_COLUMNS, "rows": rows,
            "total": ["Total", "", "", "", imp, clk, _ctr(imp, clk)],
            "placements": len(pls), "placements_live": len({r[2] for r in rows if r[4]})}


# --- Classeurs Excel ----------------------------------------------------------------------

NAVY, CHAMPAGNE, GREEN, RED, GREY = "121A25", "EDE6D4", "D8EFDF", "F6D5D2", "ECE5D3"
STATUS_FILL = {LIVE: GREEN, NO_DATA: RED, NOT_STARTED: GREY, "Partiel": "F7E6C4",
               ON_TRACK: GREEN, LATE: RED, AHEAD: "F7E6C4"}


def _pace_summary(pc: Dict) -> List[List]:
    k = pc["kpis"]
    return [["Plan média lié", pc.get("source", "")], ["Impressions prévues (total)", k["planned"]],
            ["Prévu à date", k["expected"]], ["Rythme (livré / prévu à date)", _pct(k["pace"])],
            ["Statut du rythme", k["pace_status"]], ["Projection fin de campagne", _pct(k["projection_pct"])],
            ["Budget prévu (€)", k["budget"]], ["Budget consommé estimé (€)", k["spent"]]]


def _sheet(ws, title_lines: List[str], header: List[str], rows: List[List], widths: List[int],
           status_col: Optional[int] = None, total: Optional[List] = None) -> None:
    from openpyxl.styles import Alignment, Font, PatternFill
    for i, line in enumerate(title_lines, start=1):
        ws.cell(i, 1, line).font = Font(bold=i == 1, size=13 if i == 1 else 10)
    h = len(title_lines) + 2
    for c, name in enumerate(header, start=1):
        cell = ws.cell(h, c, name)
        cell.font = Font(bold=True, color=CHAMPAGNE)
        cell.fill = PatternFill("solid", fgColor=NAVY)
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    for r, row in enumerate(rows, start=h + 1):
        for c, v in enumerate(row, start=1):
            cell = ws.cell(r, c, v)
            if isinstance(v, int):
                cell.number_format = "# ##0"
            elif isinstance(v, float):
                cell.number_format = "0.00"
            elif isinstance(v, str) and v.endswith(" %"):          # rythme, projection : centrés
                cell.alignment = Alignment(horizontal="center")
        if status_col is not None and row[status_col] in STATUS_FILL:
            ws.cell(r, status_col + 1).fill = PatternFill("solid", fgColor=STATUS_FILL[row[status_col]])
    if total:
        r = h + 1 + len(rows)
        for c, v in enumerate(total, start=1):
            cell = ws.cell(r, c, v)
            cell.font = Font(bold=True)
            cell.fill = PatternFill("solid", fgColor=GREY)
            if isinstance(v, int):
                cell.number_format = "# ##0"
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = ws.cell(h + 1, 1)
    # Impression : paysage, toutes les colonnes sur la largeur d'une page
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.auto_filter.ref = f"A{h}:{chr(64 + len(header))}{h + max(len(rows), 1)}"


def _fr(iso: str) -> str:
    d = _d(iso)
    return d.strftime("%d/%m/%Y") if d else ""


def _save(wb) -> bytes:
    wb.properties.creator = "Umnia"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _pct(v) -> str:
    return "" if v is None else f"{v:.0f} %"


def export_check(campaign: Dict, placements: List[Dict], delivery: List[Dict], today: str,
                 targets: Optional[Dict] = None) -> bytes:
    from openpyxl import Workbook
    c = check(campaign, placements, delivery, today, targets)
    k = c["kpis"]
    head = [f"Check de mise en ligne — {campaign.get('name', '')}",
            f"Annonceur : {campaign.get('advertiser', '')} · Période : {_fr(campaign.get('start'))} → "
            f"{_fr(campaign.get('end'))} · Données au {_fr(today)}"]
    wb = Workbook()
    ws = wb.active
    ws.title = "Synthèse"
    _sheet(ws, head, ["Indicateur", "Valeur"], [
        ["Impressions", k["impressions"]], ["Clics", k["clicks"]], ["CTR (%)", k["ctr"]],
        ["Emplacements avec données", f"{k['placements_live']} / {k['placements']}"],
        ["Régies avec données", f"{k['sites_live']} / {k['sites']}"],
        ["Première impression", _fr(k["first"])], ["Dernière impression", _fr(k["last"])]]
        + (_pace_summary(c["pacing"]) if c["pacing"].get("available") else []), [34, 22])
    _sheet(wb.create_sheet("Par régie"), head,
           ["Régie", "Emplacements", "Avec données", "Impressions", "Clics", "CTR (%)", "Statut"],
           [[s["site"], s["placements"], s["live"], s["impressions"], s["clicks"], s["ctr"], s["status"]]
            for s in c["sites"]], [30, 14, 14, 16, 12, 10, 20], status_col=6,
           total=["Total", k["placements"], k["placements_live"], k["impressions"], k["clicks"], k["ctr"], ""])
    _sheet(wb.create_sheet("Emplacements"), head,
           ["Régie", "Emplacement", "ID", "Format", "Début", "Fin", "Impressions", "Clics", "CTR (%)",
            "1re impression", "Dernière impression", "Statut"],
           [[r["site"], r["name"], r["id"], r["size"], _fr(r["start"]), _fr(r["end"]), r["impressions"],
             r["clicks"], r["ctr"], _fr(r["first"]), _fr(r["last"]), r["status"]] for r in c["placements"]],
           [24, 60, 12, 10, 12, 12, 14, 10, 9, 14, 16, 20], status_col=11)
    if c["pacing"].get("available"):
        pc = c["pacing"]
        _sheet(wb.create_sheet("Rythme"), head + [f"Plan média lié : {pc.get('source', '')} · niveau : {pc['kpis']['level']}"],
               ["Régie", "Emplacement", "Prévu (total)", "Prévu à date", "Livré", "Rythme", "Statut", "Projection fin",
                "Budget (€)", "Consommé estimé (€)"],
               [[r["site"], r["name"], r["pacing"]["planned"], r["pacing"]["expected"], r["pacing"]["delivered"],
                 _pct(r["pacing"]["pace"]), r["pacing"]["pace_status"], _pct(r["pacing"]["projection_pct"]),
                 r["pacing"]["budget"], r["pacing"]["spent"]] for r in c["placements"] if r.get("pacing")],
               [24, 60, 15, 15, 16, 12, 16, 16, 14, 20], status_col=6,
               total=["Total", "", pc["kpis"]["planned"], pc["kpis"]["expected"], pc["kpis"]["delivered"],
                      _pct(pc["kpis"]["pace"]), pc["kpis"]["pace_status"], _pct(pc["kpis"]["projection_pct"]),
                      pc["kpis"]["budget"], pc["kpis"]["spent"]])
    pls = {str(p.get("id")): p for p in placements}
    _sheet(wb.create_sheet("Données jour"), head,
           ["Date", "Régie", "Emplacement", "ID", "Impressions", "Clics"],
           [[_fr(r["date"]), pls.get(str(r["placement_id"]), {}).get("site", ""),
             pls.get(str(r["placement_id"]), {}).get("name", ""), str(r["placement_id"]),
             int(r.get("impressions") or 0), int(r.get("clicks") or 0)]
            for r in sorted(delivery, key=lambda r: (r.get("date", ""), str(r.get("placement_id"))))],
           [12, 24, 60, 12, 14, 10])
    return _save(wb)


def export_regie(campaign: Dict, placements: List[Dict], delivery: List[Dict], site: str, today: str) -> bytes:
    from openpyxl import Workbook
    rep = regie_report(campaign, placements, delivery, site)
    wb = Workbook()
    ws = wb.active
    ws.title = "Diffusion"
    _sheet(ws, [f"{campaign.get('advertiser', '')} — {campaign.get('name', '')} — {site}",
                f"Période : {_fr(campaign.get('start'))} → {_fr(campaign.get('end'))} · Données au {_fr(today)}"],
           rep["columns"], [[_fr(r[0])] + r[1:] for r in rep["rows"]], [12, 60, 14, 10, 14, 10, 9],
           total=rep["total"])
    return _save(wb)


# --- Mode fichier : export de rapport CM360 (sans API) -------------------------------------

EXPORT_COLUMNS = {
    "date": ["date", "jour", "day"],
    "campaign": ["campaign", "campagne"],
    "campaign_id": ["campaign id", "id campagne"],
    "advertiser": ["advertiser", "annonceur"],
    "site": ["site (cm360)", "site (dcm)", "site", "regie", "site name"],
    "site_id": ["site id (cm360)", "site id (dcm)", "site id"],
    "placement": ["placement", "emplacement", "placement name"],
    "placement_id": ["placement id", "id emplacement", "id de l'emplacement"],
    "size": ["placement size", "placement dimensions", "creative size", "taille", "format"],
    "impressions": ["impressions", "impr.", "imp."],
    "clicks": ["clicks", "clics"],
    "placement_start": ["placement start date", "date de debut de l'emplacement"],
    "placement_end": ["placement end date", "date de fin de l'emplacement"],
    "campaign_start": ["campaign start date", "date de debut de la campagne"],
    "campaign_end": ["campaign end date", "date de fin de la campagne"],
}
_EN_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _plain(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s).strip()


def _any_date(v: str) -> str:
    """2026-10-15, 15/10/2026, 15/10/26, « Oct 15, 2026 », numéro de série Excel."""
    import plan_agent
    v = str(v or "").strip()
    d = plan_agent.parse_date(v)
    if d:
        return d
    m = re.match(r"^([A-Za-z]{3})[a-z]*\.? (\d{1,2}),? (\d{4})$", v)
    if m and m.group(1).lower() in _EN_MONTHS:
        try:
            return date(int(m.group(3)), _EN_MONTHS[m.group(1).lower()], int(m.group(2))).isoformat()
        except ValueError:
            return ""
    return ""


def _int(v) -> int:
    t = re.sub(r"[\s\u202f\xa0,]", "", str(v or "")).replace("%", "")
    try:
        return int(round(float(t)))
    except ValueError:
        return 0


def _export_meta(grid, h: int) -> Dict[str, str]:
    """Bloc d'en-tête d'un export CM360 (« Date Range », « Account ID », fuseau…)."""
    meta = {}
    for row in grid[:h]:
        k = _plain(row[0]) if row else ""
        v = str(row[1]).strip() if len(row) > 1 else ""
        if k and v:
            meta[k] = v
    return meta


def parse_export(path: str, campaign_name: str = "", keyword: str = "") -> Dict:
    """Export de rapport CM360 (Report builder ou rapport hors ligne ; CSV, XLSX, XLS) ->
    campagne, emplacements, diffusion jour x emplacement : mêmes données qu'avec l'API."""
    import plan_agent
    grids = plan_agent.read_grids(path)
    best = None
    for sheet, grid in grids:
        for i, row in enumerate(grid[:60]):
            cells = [_plain(c) for c in row]
            has_metric = any(c in cells for c in ("impressions", "clicks", "clics", "total conversions", "media cost")) \
                or any(c.startswith(("active view", "video ", "unique reach")) for c in cells)
            if has_metric and any(c in cells for c in ("placement", "emplacement", "site (cm360)", "site", "date", "campaign",
                                                       "creative", "ad", "platform type", "country")):
                best = (sheet, grid, i, cells)
                break
        if best:
            break
    if not best:
        raise ValueError("Export non reconnu : il faut au moins les colonnes Impressions et Placement (ou Site / Date). "
                         "Utilisez le prompt « Check de mise en ligne » pour générer l'export dans CM360.")
    _, grid, h, cells = best
    col = {}
    for key, names in EXPORT_COLUMNS.items():
        for n in names:
            if n in cells and key not in col:
                col[key] = cells.index(n)
    get = lambda row, k: str(row[col[k]]).strip() if k in col and col[k] < len(row) else ""
    meta = _export_meta(grid, h)
    rows = []
    for row in grid[h + 1:]:
        first = " ".join(str(c) for c in row[:3]).strip().lower()
        if not first or first.startswith("grand total") or first.startswith("total"):
            continue
        if not (get(row, "placement") or get(row, "site") or get(row, "date")):
            continue
        rows.append(row)
    def camp_label(row):
        n, i = get(row, "campaign"), get(row, "campaign_id")
        return f"{n} ({i})" if n and i and i not in n else (n or i)
    campaigns: Dict[str, int] = {}
    for row in rows:
        campaigns[camp_label(row)] = campaigns.get(camp_label(row), 0) + _int(get(row, "impressions"))
    names = [c for c in sorted(campaigns, key=lambda c: -campaigns[c]) if c]
    # Campagne demandée : libellé exact, ou ID / nom contenu dans le libellé
    want = (campaign_name or "").strip()
    ids = re.findall(r"\d{5,}", want)
    chosen = next((c for c in names if c == want), "") or \
        next((c for c in names if ids and any(i in c for i in ids)), "") or \
        next((c for c in names if want and _plain(want) in _plain(c)), "") or (names[0] if names else "")
    total_rows = len(rows)
    if "campaign" in col or "campaign_id" in col:
        rows = [r for r in rows if camp_label(r) == chosen]
    kw = _plain(keyword)
    if kw:
        rows = [r for r in rows if kw in _plain(get(r, "placement")) or kw in _plain(get(r, "site"))]
    placements: Dict[str, Dict] = {}
    delivery, days, warnings = [], [], []
    starts, ends = [], []
    for row in rows:
        name = get(row, "placement") or get(row, "site") or "Campagne"
        pid = get(row, "placement_id") or name
        if pid not in placements:
            size = get(row, "size")
            m = re.search(r"(\d{2,4})\s*[x×*]\s*(\d{1,4})", size or name, re.I)
            placements[pid] = {"id": pid, "name": name, "site": get(row, "site") or "Régie inconnue",
                               "site_id": get(row, "site_id"), "size": f"{m.group(1)}x{m.group(2)}" if m else "",
                               "start": _any_date(get(row, "placement_start")), "end": _any_date(get(row, "placement_end"))}
        d = _any_date(get(row, "date"))
        if d:
            days.append(d)
        delivery.append({"date": d, "placement_id": pid, "impressions": _int(get(row, "impressions")),
                         "clicks": _int(get(row, "clicks"))})
        if get(row, "campaign_start"):
            starts.append(_any_date(get(row, "campaign_start")))
        if get(row, "campaign_end"):
            ends.append(_any_date(get(row, "campaign_end")))
    if "date" not in col:
        warnings.append("Pas de colonne Date : totaux sans détail par jour (ajoutez « Date » au rapport pour le rythme jour par jour).")
    if "placement_id" not in col:
        warnings.append("Pas de colonne Placement ID : emplacements identifiés par leur nom.")
    if "site" not in col:
        warnings.append("Pas de colonne Site (CM360) : régies inconnues.")
    if len(names) > 1:
        warnings.append(f"{len(names)} campagnes dans le fichier : « {chosen} » retenue (choix possible ci-dessous).")
    n_sites = len({p["site"] for p in placements.values()})
    account_wide = "campaign" not in col and "campaign_id" not in col and not kw and (n_sites > 25 or len(placements) > 200)
    if "campaign" not in col and "campaign_id" not in col:
        warnings.append("Pas de colonne Campaign : impossible de vérifier que l'export ne concerne que la campagne. "
                        "Ajoutez « Campaign » et « Campaign ID » aux dimensions du rapport.")
    if account_wide:
        warnings.append(f"{n_sites} sites et {len(placements)} emplacements : le filtre campagne n'a vraisemblablement pas été "
                        "appliqué par CM360 (export de tout le compte). Refaites le rapport avec un filtre Campaign ID, "
                        "ou filtrez ci-dessous par un mot présent dans les noms d'emplacements.")
    if kw:
        warnings.append(f"Filtre « {keyword} » : {len(rows)} ligne(s) sur {total_rows}.")
    clicks_only = sum(1 for d in delivery if not d["impressions"] and d["clicks"])
    if clicks_only:
        warnings.append(f"{clicks_only} ligne(s) avec des clics sans impression (click trackers / emplacements 1x1) : "
                        "comptées comme données reçues.")
    starts, ends = [x for x in starts if x], [x for x in ends if x]
    report_range = [_any_date(x.strip()) for x in meta.get("date range", "").split(" - ")] if meta.get("date range") else []
    if not starts and len(report_range) == 2 and all(report_range):
        starts, ends = [report_range[0]], [report_range[1]]
    campaign = {"id": "file", "name": chosen or os.path.splitext(os.path.basename(path))[0], "from_file": True,
                "advertiser": next((get(r, "advertiser") for r in rows if get(r, "advertiser")), ""),
                "start": min(starts) if starts else (min(days) if days else ""),
                "end": max(ends) if ends else (max(days) if days else ""),
                "dates_from": ("période du rapport" if report_range and starts == [report_range[0]] else
                               "colonnes de dates de campagne" if starts else "premier et dernier jour du fichier")}
    return {"campaign": campaign, "campaigns": names, "placements": list(placements.values()), "delivery": delivery,
            "table": export_table(grid[h], rows),
            "rows": len(rows), "total_rows": total_rows, "warnings": warnings, "account_wide": account_wide,
            "keyword": keyword, "meta": {"account": meta.get("account id", ""), "range": meta.get("date range", ""),
                                         "timezone": meta.get("report time zone", ""),
                                         "generated": meta.get("date/time generated", "")},
            "columns": {k: grid[h][i] for k, i in col.items()}}


# --- Tableau croisé : toutes les colonnes de l'export, classées dimensions / métriques -------

RATE_WORDS = ("rate", "ctr", "taux", "%", "average", "moyenne", "frequency", "frequence", "cpm", "cpc", "cpa")


def _num_cell(v) -> Optional[float]:
    t = str(v if v is not None else "").strip().replace("\u202f", "").replace("\xa0", "").replace(" ", "")
    if not t or t in ("-", "---"):
        return None
    t = t.rstrip("%")
    if re.fullmatch(r"-?\d{1,3}(,\d{3})+(\.\d+)?", t):          # 1,234,567.89
        t = t.replace(",", "")
    elif re.fullmatch(r"-?\d+,\d+", t):                           # 4,76 (décimale à la française)
        t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def export_table(header: List, rows: List[List]) -> Dict:
    """Export à plat -> colonnes typées (dimension / métrique, taux recalculé ou moyen) + lignes ;
    Semaine et Mois ajoutés quand une colonne de dates est présente."""
    cols = []
    for i, h in enumerate(header):
        label = str(h or "").strip()
        if not label:
            continue
        vals = [row[i] for row in rows if i < len(row) and str(row[i]).strip() not in ("", "-", "---")]
        nums = [_num_cell(v) for v in vals]
        numeric = bool(vals) and sum(n is not None for n in nums) >= 0.9 * len(vals)
        is_id = bool(re.search(r"(^|\W)id($|\W)", label.lower()))
        is_date = bool(vals) and not is_id and sum(bool(_any_date(str(v))) for v in vals[:50]) >= 0.8 * min(len(vals), 50) \
            and not all(re.fullmatch(r"\d+(\.\d+)?", str(v)) for v in vals[:20])
        kind = "metric" if numeric and not is_id and not is_date else "dimension"
        rate = kind == "metric" and any(w in _plain(label) for w in RATE_WORDS)
        cols.append({"i": i, "label": label, "kind": kind, "rate": rate, "date": is_date})
    date_col = next((c for c in cols if c["date"]), None)
    out_cols = [{"label": c["label"], "kind": c["kind"], "rate": c["rate"]} for c in cols]
    if date_col:
        out_cols += [{"label": "Semaine", "kind": "dimension", "rate": False, "derived": True},
                     {"label": "Mois", "kind": "dimension", "rate": False, "derived": True}]
    out_rows = []
    for row in rows:
        r = []
        for c in cols:
            v = row[c["i"]] if c["i"] < len(row) else ""
            if c["kind"] == "metric":
                n = _num_cell(v)
                r.append(0 if n is None else int(n) if n == int(n) else round(n, 4))
            elif c["date"]:
                r.append(_any_date(str(v)) or str(v))
            else:
                r.append(str(v).strip())
        if date_col:
            d = _d(_any_date(str(row[date_col["i"]]) if date_col["i"] < len(row) else ""))
            if d:
                monday = d - timedelta(days=d.weekday())
                r += [f"S{d.isocalendar()[1]:02d} · {monday.strftime('%d/%m/%Y')}", d.strftime("%Y-%m")]
            else:
                r += ["", ""]
        out_rows.append(r)
    return {"columns": out_cols, "rows": out_rows}


def export_pivot(title: str, header: List[str], rows: List[List], data: Dict) -> bytes:
    """Tableau croisé calculé dans la page + données à plat en tableau Excel (filtres, et base
    d'un tableau croisé dynamique natif : Insertion > Tableau croisé dynamique)."""
    from openpyxl import Workbook
    from openpyxl.worksheet.table import Table, TableStyleInfo
    wb = Workbook()
    ws = wb.active
    ws.title = "Tableau croisé"
    body = [r for r in rows if r and r[0] != "Total"]
    total = next((r for r in rows if r and r[0] == "Total"), None)
    _sheet(ws, [title, "Calculé par Umnia à partir de l'export. Taux recalculés (ex. CTR = clics / impressions)."],
           header, body, [34] + [16] * (len(header) - 1), total=total)
    wd = wb.create_sheet("Données")
    labels = [c["label"] for c in data.get("columns", [])]
    wd.append(labels)
    for r in data.get("rows", []):
        wd.append(r)
    if labels and data.get("rows"):
        last = f"{chr(64 + len(labels)) if len(labels) <= 26 else 'Z'}{len(data['rows']) + 1}"
        t = Table(displayName="Donnees", ref=f"A1:{last}")
        t.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
        wd.add_table(t)
        for i in range(1, min(len(labels), 26) + 1):
            wd.column_dimensions[chr(64 + i)].width = 22
    return _save(wb)


def with_plan_placements(placements: List[Dict], targets: Dict) -> List[Dict]:
    """Un export CM360 ne contient que les emplacements qui ont diffusé : ceux du plan absents du
    fichier sont ajoutés (sans données) pour que le check les signale."""
    matched = match_targets(placements, targets.get("placements") or [])
    used = {id(t) for t in matched.values()}
    extra = [{"id": f"plan:{i}", "name": t.get("name", ""), "site": t.get("site") or "Régie du plan",
              "site_id": "", "size": t.get("size", ""), "from_plan": True}
             for i, t in enumerate(targets.get("placements") or []) if id(t) not in used and t.get("name")]
    return placements + extra

