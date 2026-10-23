"""Trafficking sheet d'agence : classeur qui porte sa propre nomenclature.

Certains plans média d'agence contiennent, à côté du PM :
- un onglet modèle où les noms sont construits par formule à partir des libellés
  (« Placement Name » = Type Emplacement-Objectif-Mode d'Achat-Régie-Audience-Ciblage-…) ;
- un onglet de listes (vocabulaire autorisé par libellé : NOTORIETE, GRANDPUBLIC, SOCIODEMO…).

Ce module lit ces deux onglets, puis transforme chaque ligne du PM comme le ferait un
trafficker à la main :
- régie / partenaire : la régie, ou pour un achat via DSP le diffuseur (1re ligne du ciblage,
  ou « Youtube via DV360 » -> Youtube), le site ad server devenant la plateforme d'achat ;
- ciblage : chaque « #Type : segment » de la cellule devient un emplacement
  (type normalisé : Sociodemo -> SocioDemo, Intérêt -> Interets, LAL -> LookAlike, Data -> Custom ;
  segment nettoyé : &Geoloc retiré, + -> plus, - -> minus, 25 caractères max) ;
- format : « Détails formats » sans la durée ni la parenthèse (Preroll_20s -> PreRoll) ;
- vidéo servie en VAST (Type adserving « Video ») : asset V en 0x0, sinon tracker P en 1x1 ;
- une créative par message de la colonne « Nb messages ».
La nomenclature lue est renvoyée au format des fichiers de nomenclature d'Umnia."""
import re
import unicodedata
from typing import Dict, List, Optional, Tuple

import plan_agent

# Libellés du modèle -> jetons des motifs de nommage
LABEL_TOKENS = [
    ("type emplacement", "placement_type"), ("objectif", "objective"), ("mode d'achat", "buy"),
    ("ciblage complementaire", "targeting_detail"), ("ciblage", "targeting_type"), ("regie", "partner"),
    ("audience", "audience"), ("nom format", "format_label"), ("taille", "size"), ("device", "device"),
    ("description", "description"), ("type tracking", "tracking_type"), ("type asset", "asset_type"),
    ("nom message", "message"), ("informations complementaires", "info"),
]
NAME_LABELS = {"placement name": "placement", "line item name": "placement", "ad name": "ad",
               "creative name": "creative"}
TARGET_SYNONYMS = {"SOCIO": "SOCIODEMO", "SOCIODEMOGRAPHIQUE": "SOCIODEMO", "INTERET": "INTERETS",
                   "LAL": "LOOKALIKE", "DATA": "CUSTOM", "AFFINITE": "AFFINITAIRE", "AFFINITY": "AFFINITAIRE"}
GEO_WORDS = re.compile(r"&\s*(g[ée]oloc\w*|rural\w*|urbain\w*)", re.I)
MAX_DETAIL = 25            # « Complementary Targeting (no mandatory) max 25 characters »
DSP_HINT = re.compile(r"\bdsp\b|\bvia\b|programmatic|dv360|trade ?desk|xandr", re.I)


def _plain(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or ""))
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


def _token_of(label: str) -> str:
    p = _plain(label)
    return next((t for k, t in LABEL_TOKENS if p.startswith(k) or k in p), "")


def _camel(s: str) -> str:
    """« Grand public » -> GrandPublic ; « Notoriété » -> Notoriete."""
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    words = [w for w in re.split(r"[^A-Za-z0-9]+", s) if w]
    return "".join(w[0].upper() + w[1:] for w in words)


class Vocab:
    """Valeurs autorisées par libellé (onglet de listes), avec la casse lue dans le classeur."""

    def __init__(self, lists: Dict[str, List[str]], cased: Dict[str, str]):
        self.lists = {tok: [str(v) for v in vals] for tok, vals in lists.items()}
        self.cased = cased                         # MAJUSCULES -> forme écrite (GrandPublic…)

    def snap(self, token: str, value: str, synonyms: Optional[Dict[str, str]] = None) -> str:
        v = _camel(value)
        if not v:
            return ""
        up = v.upper()
        if synonyms:
            up = synonyms.get(up, up)
        allowed = {x.upper(): x for x in self.lists.get(token, [])}
        hit = up if up in allowed else next((a for a in allowed if a.startswith(up) and len(a) - len(up) <= 2), "")
        if not hit:
            return v
        written = self.cased.get(hit) or (allowed[hit] if allowed[hit] != hit else "")
        if written:
            return written
        return v + hit[len(up):].lower() if hit.startswith(up) else v


def _formula_refs(formula: str) -> List[str]:
    return re.findall(r"\$?([A-Z]{1,3})\$?\d+", formula or "")


def read_convention(path: str):
    """Motifs de nommage et vocabulaire, si le classeur en contient ; sinon None."""
    if not path.lower().endswith((".xlsx", ".xlsm")):
        return None
    from openpyxl import load_workbook
    from openpyxl.utils import column_index_from_string
    try:
        wb = load_workbook(path, data_only=False)
    except Exception:
        return None
    patterns: Dict[str, List[str]] = {}
    model_sheet = ""
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(min_row=1, max_row=min(ws.max_row, 80), values_only=True))
        for r, row in enumerate(rows):
            for c, v in enumerate(row):
                kind = NAME_LABELS.get(_plain(v)) if isinstance(v, str) else None
                if not kind or kind in patterns or r + 1 >= len(rows):
                    continue
                # libellé « Placement Name » au-dessus d'une formule =D14&"-"&E14&…
                formula = next((x for x in rows[r + 1] if isinstance(x, str) and x.startswith("=") and "&" in x), "")
                refs = _formula_refs(formula)
                if len(refs) < 3:
                    continue
                labels = [rows[r][column_index_from_string(L) - 1] if column_index_from_string(L) - 1 < len(rows[r]) else ""
                          for L in refs]
                tokens = [_token_of(lbl) for lbl in labels]
                if sum(1 for t in tokens if t) >= 3:
                    patterns[kind] = [t for t in tokens if t]
                    model_sheet = ws.title
    if "placement" not in patterns:
        return None
    # Onglet de listes : une ligne de libellés, les valeurs autorisées dessous
    # onglet de listes : la ligne qui porte le plus de libellés, avec des valeurs dessous
    lists: Dict[str, List[str]] = {}
    best = (0, 0)
    for ws in wb.worksheets:
        if ws.title == model_sheet:
            continue
        rows = list(ws.iter_rows(min_row=1, max_row=min(ws.max_row, 600), values_only=True))
        for r, row in enumerate(rows[:20]):
            toks = [_token_of(v) if isinstance(v, str) else "" for v in row]
            if sum(1 for t in toks if t) < 5:
                continue
            found: Dict[str, List[str]] = {}
            for c, t in enumerate(toks):
                if t and t not in found:
                    found[t] = [x[c] for x in rows[r + 1:] if c < len(x) and x[c] not in (None, "")
                                and not str(x[c]).startswith("=")]
            score = (len(found), sum(len(v) for v in found.values()))
            if score[1] >= 20 and score > best:
                best, lists = score, found
    allowed = {str(v).upper() for vals in lists.values() for v in vals}
    cased: Dict[str, str] = {}
    for ws in wb.worksheets:                      # casse écrite ailleurs dans le classeur
        for row in ws.iter_rows(values_only=True):
            for v in row:
                if isinstance(v, str) and v.upper() in allowed and v != v.upper() and v.upper() not in cased:
                    cased[v.upper()] = v
    wb.close()
    return {"patterns": patterns, "vocab": Vocab(lists, cased), "sheet": model_sheet}


def nomenclature_json(conv) -> dict:
    """Nomenclature au format Umnia (motifs {jeton}, séparateur « - », casse conservée)."""
    def pat(kind):
        return "-".join("{" + t + "}" for t in conv["patterns"].get(kind, []))
    rules = {"placement": pat("placement"),
             # une annonce par emplacement : les messages diffèrent d'une audience à l'autre
             "ad": "{placement_name}",
             "creative": pat("creative") or "{asset_type}-{format_label}-{size}-{message}",
             "options": {"separator": "-", "case": "", "strip_accents": True, "max_length": 255, "forbidden": []}}
    return {"defaults": rules}


# --- Lignes du PM --------------------------------------------------------------------------

def _col(headers: List[str], *keys: str) -> int:
    norm = [_plain(h).replace("\n", " ") for h in headers]
    for k in keys:
        for i, h in enumerate(norm):
            if re.sub(r"\s+", " ", h).startswith(k):
                return i
    return -1


def _targetings(cell: str) -> Tuple[str, List[Tuple[str, str]]]:
    """« Netflix / Jeune / #SocioDemo : HF1834&Geoloc » -> (1re ligne libre, [(type, segment)])."""
    lines = [l.strip() for l in str(cell or "").splitlines() if l.strip()]
    tags, free = [], []
    for l in lines:
        m = re.match(r"#\s*([^:]+?)\s*:\s*(.+)$", l)
        if m:
            tags.append((m.group(1), m.group(2)))
        else:
            free.append(l)
    return (free[0] if free else ""), tags


def clean_detail(seg: str) -> str:
    """HF1834&Geoloc -> HF1834 ; 60+CSP-&rural -> 60plusCSPminus ; HF63+ -> HF63 ; 25 caractères max."""
    s = GEO_WORDS.sub("", seg)
    # « + » en fin de critère (HF63+) tombe ; ailleurs il devient « plus » (60+CSP -> 60plusCSP)
    parts = [re.sub(r"\+\s*$", "", p.strip()) for p in s.split("&")]
    s = " ".join(p.replace("+", "plus").replace("-", "minus") for p in parts)
    s = _camel(s)
    # trop long : on retire d'abord les qualificatifs CSP, puis on abrège, en dernier on coupe
    for short in (lambda x: re.sub(r"CSP(minus|plus|moins)?$", "", x) if not x.endswith("CSP") else x,
                  lambda x: x.replace("Affinitaire", "Aff"), lambda x: x.replace("Audience", "Aud")):
        if len(s) > MAX_DETAIL:
            s = short(s)
    return s[:MAX_DETAIL]


def _partner(support: str, regie: str, free_line: str) -> Tuple[str, str]:
    """(partenaire écrit dans le nom, site ad server)."""
    support = re.sub(r"\(.*?\)", "", support or "").strip()
    via = re.match(r"(.+?)\s+via\s+", support, re.I)
    is_dsp = bool(DSP_HINT.search(support)) or "programmatic" in _plain(regie)
    if is_dsp:
        name = via.group(1) if via else (free_line or support)
        return name, (regie if regie and "programmatic" in _plain(regie) else support)
    return support, regie or support


def _partner_token(name: str) -> str:
    name = re.sub(r"\s*\+\s*$", "", name.strip())             # « TF1 + » -> TF1
    name = re.sub(r"\s+plus\b", "Plus", name, flags=re.I)      # « Canal plus » -> CanalPlus
    return _camel(name)


def build_rows(path: str, grids, conv, highlights=None) -> Tuple[List[Dict[str, str]], List[str]]:
    sheet, grid, h = plan_agent.find_table([(n, g) for n, g in grids if n != conv["sheet"]])
    headers = [str(x or "") for x in grid[h]]
    vocab = conv["vocab"]
    context = plan_agent.read_context(grid[:h])
    c = {k: _col(headers, *v) for k, v in {
        "objective": ("objectif",), "audience": ("audience",), "support": ("support",), "regie": ("regie",),
        "formats": ("formats",), "messages": ("nb messages", "nb  messages", "messages"),
        "details": ("details formats", "detail format"), "placement": ("emplacement",), "device": ("device",),
        "targeting": ("ciblages", "ciblage"), "start": ("date debut", "debut"), "end": ("date fin", "fin"),
        "buy": ("mode d'achat", "mode  d'achat", "mode"), "volume": ("volume",), "budget": ("budget net", "budget"),
        "adserving": ("type adserving",)}.items()}
    get = lambda raw, k: (raw[c[k]] if c[k] >= 0 and c[k] < len(raw) else "").strip()
    report = [f"Trafficking sheet d'agence : nomenclature lue dans l'onglet « {conv['sheet']} » "
              f"(emplacement = {'-'.join(conv['patterns']['placement'])}), vocabulaire lu dans le classeur.",
              f"Feuille « {sheet} », en-tête ligne {h + 1}."]
    rows: List[Dict[str, str]] = []
    blanks = 0
    for raw in grid[h + 1:]:
        if not get(raw, "support"):
            blanks += 1
            if blanks >= 3 and rows:
                break
            continue
        blanks = 0
        free, tags = _targetings(get(raw, "targeting"))
        name, site = _partner(get(raw, "support"), get(raw, "regie"), free)
        video = "video" in _plain(get(raw, "adserving"))
        details = re.sub(r"\(.*?\)", "", get(raw, "details") or get(raw, "formats")).strip()
        fmt = re.sub(r"_\d+\s*s(ec)?$", "", details, flags=re.I) or get(raw, "formats")
        messages = [m.strip() for m in get(raw, "messages").splitlines() if m.strip()] or [""]
        base = {
            "advertiser_name": (context.get("advertiser_name") or ("", ""))[0],
            "campaign_name": (context.get("campaign_name") or ("", ""))[0],
            "campaign_start": plan_agent.parse_date(get(raw, "start")) or get(raw, "start"),
            "campaign_end": plan_agent.parse_date(get(raw, "end")) or get(raw, "end"),
            "objective": vocab.snap("objective", get(raw, "objective")),
            "audience": vocab.snap("audience", get(raw, "audience")),
            "partner": vocab.snap("partner", _partner_token(name)),
            "site_name": _camel(site) if "programmatic" in _plain(site) else site.strip(),
            "placement_type": vocab.snap("placement_type", get(raw, "placement")[:1]),
            "buy": get(raw, "buy"), "pricing_type": get(raw, "buy"),
            "format_label": vocab.snap("format_label", fmt),
            "size": "0x0" if video else "1x1", "asset_type": "V" if video else "P",
            "placement_category": "video" if video else "tracking",
            "device": vocab.snap("device", get(raw, "device")),
        }
        tags = tags or [("", "")]
        for k, (ttype, seg) in enumerate(tags):
            line = dict(base, targeting_type=vocab.snap("targeting_type", ttype, TARGET_SYNONYMS),
                        targeting_detail=clean_detail(seg), targeting=f"#{ttype} : {seg}" if ttype else free)
            # budget et volume portés par le premier ciblage seulement (comme la trafficking sheet)
            budget, volume = (get(raw, "budget"), get(raw, "volume")) if k == 0 else ("", "")
            pname = "-".join(line.get(t, "") for t in conv["patterns"]["placement"] if line.get(t, ""))
            for j, msg in enumerate(messages):
                r = dict(line, placement_name=pname, ad_name=pname,
                         message=re.sub(r"\s+", "", msg).upper(),
                         budget_eur=budget if j == 0 else "", objective_impressions=volume if j == 0 else "",
                         line_budget_eur=budget, line_volume=volume)
                r["creative_name"] = "-".join(x for x in (r["asset_type"], r["format_label"], r["size"], r["message"]) if x)
                rows.append(r)
    n_pl = len({r["placement_name"] for r in rows})
    report.append(f"{n_pl} emplacement(s) (un par ciblage « #… : … ») et {len(rows)} créative(s) "
                  "(une par message de la colonne « Nb messages »).")
    report.append("Achats via DSP : diffuseur écrit dans le nom (1re ligne du ciblage ou « X via DSP »), "
                  "site ad server = plateforme d'achat. Vidéo servie en VAST (Type adserving « Video ») : 0x0.")
    return rows, report
