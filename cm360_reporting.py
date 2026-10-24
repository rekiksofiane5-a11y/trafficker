
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cm360_reporting.py
==================
Couche de REPORTING (lecture) multi-plateformes — le complément du moteur de
trafficking cm360_trafficker.py :

    --platform mock    Simulation locale, aucun accès requis
    --platform cm360   Campaign Manager 360 — Reports API (v5, même service)
    --platform adform  Adform (à compléter avec un accès réel)

Fonctions :
    - pull : rapports de diffusion (impressions / clics par campagne et
      emplacement) sur la période de vol du plan média ;
    - reconcile : comparaison avec le plan (colonne optionnelle
      `objective_impressions`) -> pacing : OK / EN RETARD / EN AVANCE ;
    - sortie texte (lisible) ou JSON (--json rapport.json).

Le plan média peut contenir une colonne optionnelle `objective_impressions`
(objectif d'impressions par campagne) pour activer le pacing.

Utilisation :
    python cm360_reporting.py plan_media.csv --platform mock
    python cm360_reporting.py plan_media.csv --platform cm360 \\
        --service-account cle.json --profile-id 1234567
    python cm360_reporting.py plan_media.csv --platform mock --json rapport.json
"""

import argparse
import csv
import io
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Dict, List, Optional, Tuple

from cm360_trafficker import (
    cm360_authenticate,
    cm360_pick_profile,
)


# ---------------------------------------------------------------------------
# 1. Modèle de données
# ---------------------------------------------------------------------------

@dataclass
class PlacementDelivery:
    name: str
    impressions: int = 0
    clicks: int = 0
    spend: float = 0.0             # dépense média (devise du compte)

@dataclass
class CampaignDelivery:
    name: str
    impressions: int = 0
    clicks: int = 0
    spend: float = 0.0             # dépense média (devise du compte)
    placements: Dict[str, PlacementDelivery] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 2. Interface d'adaptateur de reporting
# ---------------------------------------------------------------------------

class ReportingAdapter:
    """Contrat commun : lire la diffusion sur une plateforme, sans écrire."""
    name = "base"

    def __init__(self, log: Callable[[str], None] = print):
        self.log = log

    def check_access(self) -> None:
        raise NotImplementedError

    def pull(self, campaign_names: List[str], start: str, end: str
             ) -> List[CampaignDelivery]:
        """Renvoie la diffusion agrégée par campagne (placements inclus)."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# 3. Adaptateur CM360 (Reports API v5 — même service dfareporting)
# ---------------------------------------------------------------------------

class CM360ReportingAdapter(ReportingAdapter):
    """Campaign Manager 360 — Reports API (v5).

    Flux : reports().insert (type STANDARD, CSV) -> interrogation des fichiers
    du rapport -> téléchargement -> parsing. Le rapport étant asynchrone côté
    Google, on interroge le statut jusqu'à obtention du fichier.
    """
    name = "cm360"

    def __init__(self, service, profile_id: int, log: Callable[[str], None] = print):
        super().__init__(log=log)
        self.svc = service
        self.profile = profile_id

    def _call(self, fn, **kwargs):
        # Retry simple sur 429/5xx, même logique que le moteur de trafficking
        for attempt in range(5):
            try:
                return fn(**kwargs).execute()
            except Exception as e:
                status = getattr(getattr(e, "resp", None), "status", None) \
                    or getattr(e, "status_code", None)
                if status in (429, 500, 502, 503) and attempt < 4:
                    time.sleep(2 ** attempt)
                    continue
                raise

    def check_access(self) -> None:
        rep = self._call(self.svc.reports().list, profileId=self.profile,
                         maxResults=1)
        self.log("Accès Reports API OK "
                 f"({len(rep.get('items', []))} rapport(s) récent(s) visible(s)).")

    def pull(self, campaign_names: List[str], start: str, end: str
             ) -> List[CampaignDelivery]:
        body = {
            "displayName": "Umnia - rapport de diffusion",
            "type": "STANDARD",
            "format": "CSV",
            "criteria": {
                "dateRange": {"startDate": start, "endDate": end},
                "dimensions": [{"name": "campaign"}, {"name": "placement"}],
                "metricNames": ["impressions", "clicks", "mediaCost"],
            },
        }
        rep = self._call(self.svc.reports().insert,
                         profileId=self.profile, body=body)
        self.log(f"Rapport CM360 créé (id {rep['id']}), génération en cours...")

        # Le rapport est asynchrone : on attend le fichier (statuts à valider
        # avec un accès réel — COMPLETED/READY selon la version).
        ready = []
        for _ in range(60):
            files = self._call(self.svc.reportFiles().list,
                               profileId=self.profile,
                               reportId=rep["id"]).get("items", [])
            ready = [f for f in files
                     if f.get("status") in ("COMPLETED", "READY")]
            if ready:
                break
            time.sleep(5)
        if not ready:
            raise RuntimeError("Le rapport CM360 n'a pas été généré à temps.")

        f0 = ready[0]
        self.log(f"Fichier prêt (id {f0['id']}), téléchargement...")
        data = self.svc.reportFiles().get(
            profileId=self.profile, reportId=rep["id"],
            fileId=f0["id"], alt="media").execute()
        if isinstance(data, str):
            data = data.encode()
        return _parse_delivery_csv(data, campaign_names)


def _parse_delivery_csv(data: bytes,
                        campaign_names: Optional[List[str]] = None
                        ) -> List[CampaignDelivery]:
    """Parse l'export CSV (Campaign, Placement, Impressions, Clicks[, Media Cost]).
    La colonne « Media Cost » est optionnelle (nom à valider avec un accès réel).
    Filtre côté client sur les campagnes demandées."""
    wanted = {c.lower() for c in (campaign_names or [])}
    campaigns: Dict[str, CampaignDelivery] = {}
    for r in csv.DictReader(io.StringIO(data.decode("utf-8-sig"))):
        cname = (r.get("Campaign") or "").strip()
        pname = (r.get("Placement") or "").strip()
        if not cname or (wanted and cname.lower() not in wanted):
            continue
        camp = campaigns.setdefault(cname, CampaignDelivery(name=cname))
        pl = PlacementDelivery(
            name=pname,
            impressions=int(float(r.get("Impressions") or 0)),
            clicks=int(float(r.get("Clicks") or 0)),
            spend=float(r.get("Media Cost") or 0))
        camp.placements[pname] = pl
        camp.impressions += pl.impressions
        camp.clicks += pl.clicks
        camp.spend += pl.spend
    return list(campaigns.values())


# ---------------------------------------------------------------------------
# 4. Adaptateur Adform (à compléter avec un accès réel)
# ---------------------------------------------------------------------------

class AdformReportingAdapter(ReportingAdapter):
    """Adform — reporting via l'API externe (à implémenter avec un accès
    réel : endpoint reporting/insights de l'API Adform)."""
    name = "adform"

    def check_access(self) -> None:
        raise NotImplementedError("AdformReportingAdapter : à implémenter avec "
                                  "l'accès réel (endpoint reporting Adform).")

    def pull(self, campaign_names, start, end):
        raise NotImplementedError("AdformReportingAdapter : à implémenter avec "
                                  "l'accès réel (endpoint reporting Adform).")


# ---------------------------------------------------------------------------
# 5. Adaptateur mock (démo locale, déterministe)
# ---------------------------------------------------------------------------

class MockReportingAdapter(ReportingAdapter):
    """Simule des volumes de diffusion déterministes (même nom -> mêmes
    chiffres), pour les démos et les tests de la couche réconciliation."""
    name = "mock"
    plan_placements: Dict[str, List[str]] = {}

    def check_access(self) -> None:
        self.log("Reporting MOCK (démo) : accès simulé, aucun compte requis.")

    def pull(self, campaign_names, start, end):
        out = []
        for name in campaign_names:
            seed = sum(ord(c) for c in name)
            camp = CampaignDelivery(name=name)
            camp.impressions = 250_000 + (seed % 750_000)
            camp.clicks = int(camp.impressions * ((seed % 30) + 5) / 1000)
            cpm = 2.0 + (seed % 60) / 10          # CPM fictif entre 2 et 8
            camp.spend = round(camp.impressions * cpm / 1000, 2)
            # Emplacements du plan (fournis par report_for_plan), répartis à parts égales
            pls = self.plan_placements.get(name, [])
            for pname in pls:
                share = 1.0 / len(pls)
                pl = PlacementDelivery(name=pname,
                                       impressions=int(camp.impressions * share),
                                       clicks=int(camp.clicks * share),
                                       spend=round(camp.spend * share, 2))
                camp.placements[pname] = pl
            out.append(camp)
        return out


# ---------------------------------------------------------------------------
# 6. Fabrique
# ---------------------------------------------------------------------------

def build_reporting_adapter(platform: str = "mock",
                            log: Callable[[str], None] = print,
                            service_account: str = "",
                            profile_id: Optional[int] = None) -> ReportingAdapter:
    """Construit l'adaptateur de reporting : mock | cm360 | adform."""
    if platform in ("mock", "demo"):
        return MockReportingAdapter(log=log)
    if platform == "cm360":
        if not service_account:
            sys.exit("CM360 : compte de service requis (--service-account "
                     "ou CM360_SA_KEY). Sinon testez avec --platform mock.")
        service = cm360_authenticate(service_account)
        pid = cm360_pick_profile(service, profile_id)
        return CM360ReportingAdapter(service, pid, log=log)
    if platform == "adform":
        return AdformReportingAdapter(log=log)
    sys.exit(f"Plateforme inconnue : '{platform}' (mock | cm360 | adform)")


# ---------------------------------------------------------------------------
# 7. Plan -> vols, objectifs ; réconciliation (pacing)
# ---------------------------------------------------------------------------

def extract_flights(rows: List[Dict[str, str]]
                    ) -> Dict[str, Tuple[str, str, Optional[int]]]:
    """Extrait, par campagne : (date début, date fin, objectif d'impressions).
    L'objectif vient de la colonne optionnelle `objective_impressions`."""
    flights: Dict[str, Tuple[str, str, Optional[int]]] = {}
    for r in rows:
        get = lambda k, r=r: (r.get(k) or "").strip()
        name = get("campaign_name")
        if not name:
            continue
        obj = get("objective_impressions")
        flights[name] = (get("campaign_start"), get("campaign_end"),
                         int(float(obj)) if obj else None)
    return flights


def extract_budgets(rows: List[Dict[str, str]]) -> Dict[str, float]:
    """Budget média (€) par campagne, colonne optionnelle `budget_eur`.
    Le budget est celui de la campagne : la dernière valeur renseignée sur
    ses lignes est retenue (inutile de la répéter, mais ça ne gêne pas)."""
    budgets: Dict[str, float] = {}
    for r in rows:
        name = (r.get("campaign_name") or "").strip()
        raw = (r.get("budget_eur") or "").strip().replace(" ", "").replace(",", ".")
        if name and raw:
            try:
                budgets[name] = float(raw)
            except ValueError:
                pass
    return budgets


def _n(v) -> str:
    """Nombre avec espace comme séparateur de milliers (sans décimales)."""
    return f"{v:,.0f}".replace(",", " ")


def _pacing_status(ratio: float) -> str:
    return "OK" if 0.8 <= ratio <= 1.2 else "EN RETARD" if ratio < 0.8 else "EN AVANCE"


def reconcile(deliveries: List[CampaignDelivery],
              flights: Dict[str, Tuple[str, str, Optional[int]]],
              today: Optional[date] = None,
              budgets: Optional[Dict[str, float]] = None) -> List[str]:
    """Compare la diffusion au plan :
    - pacing = livré / attendu, où attendu = objectif x fraction du vol écoulée ;
    - statuts : OK (0.8-1.2), EN RETARD (<0.8), EN AVANCE (>1.2) ;
    - budget (€, colonne optionnelle `budget_eur`) : pacing dépense = dépensé /
      (budget x fraction du vol écoulée), mêmes statuts ;
    - vol pas encore commencé : « NON DÉMARRÉE » (pas de pacing) ;
    - sans objectif : livraison brute affichée (pas de pacing)."""
    today = today or date.today()
    # Index insensible à la casse : nom -> (start, end, objectif)
    index = {k.lower(): v for k, v in flights.items()}
    budget_index = {k.lower(): v for k, v in (budgets or {}).items()}
    lines = []
    for d in deliveries:
        start_s, end_s, objective = index.get(d.name.lower(), ("", "", None))
        ctr = (d.clicks / d.impressions * 100) if d.impressions else 0.0
        line = (f"{d.name} : {_n(d.impressions)} impressions, {_n(d.clicks)} clics "
                f"(CTR {ctr:.2f}%)")
        budget = budget_index.get(d.name.lower())
        if objective or budget:
            try:
                start = date.fromisoformat(start_s)
                end = date.fromisoformat(end_s)
                total = (end - start).days or 1
                elapsed = max(0, min(total, (today - start).days))
                if elapsed == 0:
                    line += " — vol non démarré [NON DÉMARRÉE]"
                else:
                    if objective:
                        ratio = d.impressions / (objective * elapsed / total)
                        line += (f" — objectif {_n(objective)} : {elapsed}/{total} j de vol, "
                                 f"pacing {ratio * 100:.0f}% [{_pacing_status(ratio)}]")
                    if budget:
                        ratio = d.spend / (budget * elapsed / total)
                        line += (f" — budget {_n(budget)} € : dépensé {_n(d.spend)} €, "
                                 f"pacing dépense {ratio * 100:.0f}% [{_pacing_status(ratio)}]")
            except (ValueError, TypeError):
                pass
        lines.append(line)
    return lines


# ---------------------------------------------------------------------------
# 8. Point d'entrée CLI
# ---------------------------------------------------------------------------

def report_for_plan(rows: List[Dict[str, str]], adapter: ReportingAdapter,
                    log: Callable[[str], None] = print
                    ) -> Tuple[List[CampaignDelivery], List[str]]:
    """Fonction réutilisable (serveur MCP, UI...) : diffusion + réconciliation
    pour toutes les campagnes d'un plan déjà lu."""
    flights = extract_flights(rows)
    names = list(flights.keys())
    if not names:
        raise ValueError("Aucune campagne trouvée dans le plan.")
    starts = [f[0] for f in flights.values() if f[0]]
    ends = [f[1] for f in flights.values() if f[1]]
    if isinstance(adapter, MockReportingAdapter):
        pp: Dict[str, List[str]] = {}
        for r in rows:
            c, pl = (r.get("campaign_name") or "").strip(), (r.get("placement_name") or "").strip()
            if c and pl and pl not in pp.setdefault(c, []):
                pp[c].append(pl)
        adapter.plan_placements = pp
    deliveries = adapter.pull(names, min(starts), max(ends))
    return deliveries, reconcile(deliveries, flights, budgets=extract_budgets(rows))


def delivery_to_dict(platform: str, deliveries: List[CampaignDelivery],
                     flags: List[str]) -> dict:
    """Représentation JSON commune (CLI --json, MCP, UI)."""
    return {
        "platform": platform,
        "campaigns": [
            {"name": d.name, "impressions": d.impressions, "clicks": d.clicks,
             "spend": round(d.spend, 2),
             "placements": [{"name": p.name, "impressions": p.impressions,
                             "clicks": p.clicks, "spend": round(p.spend, 2)}
                            for p in d.placements.values()]}
            for d in deliveries],
        "reconciliation": flags,
    }


def main():
    ap = argparse.ArgumentParser(
        description="Reporting de diffusion multi-plateformes (mock / CM360 / "
                    "Adform) + réconciliation avec le plan média.")
    ap.add_argument("plan", help="Fichier du plan média (.csv/.xlsx) ou URL "
                                 "Google Sheet partagée")
    ap.add_argument("--platform", choices=["mock", "cm360", "adform"],
                    default="mock")
    ap.add_argument("--service-account", default=os.environ.get("CM360_SA_KEY", ""),
                    help="Chemin du JSON du compte de service Google (CM360)")
    ap.add_argument("--profile-id", type=int,
                    default=int(os.environ["CM360_PROFILE_ID"])
                    if os.environ.get("CM360_PROFILE_ID") else None)
    ap.add_argument("--check", action="store_true",
                    help="Diagnostic de l'accès reporting seulement")
    ap.add_argument("--json", default="",
                    help="Fichier JSON de sortie (livraisons + réconciliation)")
    args = ap.parse_args()

    if args.check:
        adapter = build_reporting_adapter(
            platform=args.platform, log=print,
            service_account=args.service_account, profile_id=args.profile_id)
        adapter.check_access()
        return

    from cm360_trafficker import load_rows_from_path, resolve_plan_source
    src = resolve_plan_source((args.plan or "").strip())
    try:
        rows = load_rows_from_path(src)
    finally:
        # RGPD : purge immédiate du fichier temporaire (export Google Sheet)
        if src != args.plan:
            os.remove(src)

    adapter = build_reporting_adapter(
        platform=args.platform, log=print,
        service_account=args.service_account, profile_id=args.profile_id)
    print(f"\n=== Rapport de diffusion [{adapter.name}] ===")
    deliveries, flags = report_for_plan(rows, adapter, log=print)
    for line in flags:
        print(line)
    n_pl = sum(len(d.placements) for d in deliveries)
    print(f"\n{len(deliveries)} campagne(s), {n_pl} emplacement(s) couvert(s).")

    if args.json:
        payload = delivery_to_dict(adapter.name, deliveries, flags)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"Rapport écrit : {args.json}")


if __name__ == "__main__":
    main()

