# -*- coding: utf-8 -*-
"""Contrôle des créatives selon la base de specs CM360 (specs/cm360_creative_specs.json,
extraite de specs/cm360_specs_creatives.xlsx — sources : aide Campaign Manager 360).

Pour chaque fichier créatif fourni : extension acceptée, poids max, dimensions,
ratio, durée et codec (vidéo), règles HTML5 (click tag, pas de %, pas de .zip
imbriqué, 100 fichiers max, types autorisés, pas de stockage local, pas d'URL http).
Lecture des en-têtes de fichiers en Python pur (PNG, GIF, JPEG, MP4/MOV, ZIP) :
fonctionne aussi dans le navigateur (Pyodide).

Niveaux : « erreur » (refusé par CM360, bloque l'envoi) ; « alerte » (accepté mais
hors recommandation).
"""
import json
import os
import re
import struct
import zipfile
from typing import Dict, List, Optional, Tuple

SPECS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "specs", "cm360_creative_specs.json")

MB = 1024 * 1024
# Règles machine, alignées sur la base de specs (identifiant -> règle)
RULES: Dict[str, dict] = {
    "Display – multidevice – Image": {
        "ext": {"gif", "jpg", "jpeg", "png", "wbmp"}, "max_bytes": int(9.5 * MB), "max_dim": 4000},
    "Display – multidevice – HTML5": {
        "ext": {"zip", "adz"}, "max_bytes": 10 * MB, "warn_bytes": int(9.5 * MB), "max_files": 100,
        "inner_ext": {"html", "htm", "js", "css", "jpg", "jpeg", "gif", "png", "json", "xml", "svg",
                      "eot", "otf", "ttf", "woff", "woff2"}},
    "Vidéo in-stream – multidevice/CTV – Source": {
        "ext": {"avi", "mov", "mp4", "m4v", "mpeg", "mpg", "webm", "wmv"}, "max_bytes": 1024 * MB,
        "durations": {15, 30},
        "sizes": {(1280, 720), (1920, 1080), (1440, 1080), (720, 1280), (1080, 1920), (1080, 1440),
                  (720, 720), (1080, 1080), (1920, 1920)},
        "ratios": {(16, 9), (4, 3), (9, 16), (3, 4), (1, 1)}},
    "Audio in-stream – desktop/mobile – Audio": {
        "ext": {"mp3", "oga", "ogg", "ogv"}, "max_bytes": 1024 * MB},
}
# Type de créative Trafficker -> spec CM360
CTYPE_SPEC = {
    "IMAGE": "Display – multidevice – Image",
    "HTML5": "Display – multidevice – HTML5",
    "VIDEO": "Vidéo in-stream – multidevice/CTV – Source",
    "AUDIO": "Audio in-stream – desktop/mobile – Audio",
}


def load_specs() -> List[dict]:
    with open(SPECS_PATH, encoding="utf-8") as f:
        return json.load(f)


def spec_summary(ctype: str) -> Optional[dict]:
    """Rappel lisible de la spec d'un type de créative (pour l'aperçu)."""
    sid = CTYPE_SPEC.get(ctype)
    if not sid:
        return None
    for s in load_specs():
        if s["Identifiant"] == sid:
            keep = ("Format", "Poids max", "Dimensions", "Ratio", "Durée", "Codec / Fréquence",
                    "Nb fichiers max", "Recommandé", "Règles clés", "URL source (globale)")
            return {"id": sid, **{k: s.get(k) for k in keep if s.get(k) not in (None, "", "—")}}
    return None


# --- Lecture des en-têtes ------------------------------------------------------------

def image_size(data: bytes) -> Optional[Tuple[int, int]]:
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        return struct.unpack("<HH", data[6:10])
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return w, h
            seg = struct.unpack(">H", data[i + 2:i + 4])[0]
            i += 2 + seg
    return None


def _boxes(data: bytes, start: int, end: int):
    i = start
    while i + 8 <= end:
        size, kind = struct.unpack(">I4s", data[i:i + 8])
        hdr = 8
        if size == 1 and i + 16 <= end:
            size = struct.unpack(">Q", data[i + 8:i + 16])[0]
            hdr = 16
        elif size == 0:
            size = end - i
        if size < hdr:
            return
        yield kind, i + hdr, min(i + size, end)
        i += size


def mp4_info(data: bytes) -> dict:
    """Durée (s), dimensions de la piste vidéo et codec, depuis les boîtes MP4/MOV."""
    info: dict = {}
    for kind, s, e in _boxes(data, 0, len(data)):
        if kind != b"moov":
            continue
        for k2, s2, e2 in _boxes(data, s, e):
            if k2 == b"mvhd":
                v = data[s2]
                if v == 1:
                    ts, dur = struct.unpack(">IQ", data[s2 + 20:s2 + 32])
                else:
                    ts, dur = struct.unpack(">II", data[s2 + 12:s2 + 20])
                if ts:
                    info["duration"] = dur / ts
            elif k2 == b"trak":
                for k3, s3, e3 in _boxes(data, s2, e2):
                    if k3 == b"tkhd":
                        w, h = struct.unpack(">II", data[e3 - 8:e3])
                        if w and h and "width" not in info:
                            info["width"], info["height"] = w >> 16, h >> 16
    for codec in (b"avc1", b"avc3", b"hvc1", b"hev1", b"vp09", b"av01", b"mp4v"):
        if codec in data[:4 * MB] or codec in data[-4 * MB:]:
            info["codec"] = codec.decode()
            break
    return info


# --- Contrôles -------------------------------------------------------------------------

def _f(level: str, msg: str) -> Tuple[str, str]:
    return level, msg


def _ratio_ok(w: int, h: int, ratios) -> bool:
    return any(abs(w / h - a / b) < 0.02 for a, b in ratios)


def check_file(path: str, ctype: str, placement_size: Optional[Tuple[int, int]] = None
               ) -> List[Tuple[str, str]]:
    """Contrôle un fichier créatif contre la spec CM360 de son type."""
    sid = CTYPE_SPEC.get(ctype)
    if not sid:
        return []
    rule = RULES[sid]
    out: List[Tuple[str, str]] = []
    name = os.path.basename(path)
    ext = os.path.splitext(name)[1].lower().lstrip(".")
    if not os.path.isfile(path):
        return [_f("alerte", f"{name} : fichier non fourni, specs non vérifiées "
                             "(joignez les créatives pour le contrôle).")]
    size = os.path.getsize(path)
    if ext not in rule["ext"]:
        out.append(_f("erreur", f"{name} : extension .{ext} refusée ({sid} : "
                                f"{', '.join(sorted(rule['ext'])).upper()})."))
    if size > rule["max_bytes"]:
        out.append(_f("erreur", f"{name} : {size / MB:.1f} Mo, au-delà de {rule['max_bytes'] / MB:g} Mo."))
    elif rule.get("warn_bytes") and size > rule["warn_bytes"]:
        out.append(_f("alerte", f"{name} : {size / MB:.1f} Mo, proche de la limite (9,5 Mo recommandés)."))
    with open(path, "rb") as fh:
        if size <= 64 * MB:
            data = fh.read()
        else:                       # gros fichier vidéo : début et fin suffisent (boîtes moov)
            data = fh.read(8 * MB)
            fh.seek(-8 * MB, 2)
            data += fh.read()

    if ctype == "IMAGE":
        dims = image_size(data)
        if dims:
            w, h = dims
            if w > rule["max_dim"] or h > rule["max_dim"]:
                out.append(_f("alerte", f"{name} : {w}×{h}, au-delà de 4000×4000 (réduction automatique, "
                                        "risque sur le ratio)."))
            if placement_size and placement_size != (1, 1):
                pw, ph = placement_size
                if abs(w / h - pw / ph) > 0.02:
                    out.append(_f("alerte", f"{name} : ratio {w}×{h} différent de l'emplacement {pw}×{ph} "
                                            "(redimensionnement avec conservation des proportions)."))
                elif w < pw:
                    out.append(_f("alerte", f"{name} : {w}×{h} plus petit que l'emplacement {pw}×{ph} "
                                            f"(recommandé : jusqu'à {pw * 2}×{ph * 2})."))
        elif ext in ("png", "gif", "jpg", "jpeg"):
            out.append(_f("erreur", f"{name} : image illisible ou corrompue."))

    elif ctype == "VIDEO" and ext in ("mp4", "mov", "m4v"):
        info = mp4_info(data)
        d = info.get("duration")
        if d is not None and round(d + 0.49) not in rule["durations"]:
            out.append(_f("alerte", f"{name} : durée {d:.1f} s (recommandé : 15 ou 30 s ; "
                                    "durée arrondie à la seconde supérieure)."))
        if "width" in info:
            w, h = info["width"], info["height"]
            if (w, h) not in rule["sizes"]:
                out.append(_f("alerte", f"{name} : {w}×{h} hors tailles recommandées "
                                        "(1280×720, 1920×1080, 1440×1080 ; portrait/carré équivalents)."))
            if not _ratio_ok(w, h, rule["ratios"]):
                out.append(_f("alerte", f"{name} : ratio {w}:{h} hors 16:9, 4:3, 9:16, 3:4."))
        if info.get("codec") and info["codec"] not in ("avc1", "avc3"):
            out.append(_f("alerte", f"{name} : codec {info['codec']} (H.264 recommandé)."))
        if not info:
            out.append(_f("alerte", f"{name} : en-tête vidéo illisible, durée et format non vérifiés."))
    elif ctype == "VIDEO" and ext == "webm":
        out.append(_f("alerte", f"{name} : WebM accepté mais plus transcodé par CM360 depuis 2022."))

    elif ctype == "HTML5":
        out += _check_html5(path, name, rule)
    return out


def _check_html5(path: str, name: str, rule: dict) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        return [_f("erreur", f"{name} : archive HTML5 illisible.")]
    files = [i for i in z.infolist() if not i.is_dir() and not i.filename.startswith("__MACOSX/")]
    if len(files) > rule["max_files"]:
        out.append(_f("erreur", f"{name} : {len(files)} fichiers (100 maximum)."))
    for i in files:
        base = i.filename.rsplit("/", 1)[-1]
        ext = base.rsplit(".", 1)[-1].lower() if "." in base else ""
        if "%" in i.filename:
            out.append(_f("erreur", f"{name} : « {i.filename} » contient un % (interdit)."))
        if ext in ("zip", "adz"):
            out.append(_f("erreur", f"{name} : .zip imbriqué « {i.filename} » (interdit)."))
        elif ext not in rule["inner_ext"] and base not in (".DS_Store",):
            out.append(_f("erreur", f"{name} : type de fichier non autorisé « {i.filename} »."))
    htmls = [i for i in files if i.filename.lower().endswith((".html", ".htm"))]
    if not htmls:
        return out + [_f("erreur", f"{name} : aucun fichier HTML dans l'archive.")]
    text = ""
    for i in files:
        if i.filename.lower().endswith((".html", ".htm", ".js")):
            text += z.read(i).decode("utf-8", errors="replace") + "\n"
    if not re.search(r"clicktag", text, re.I):
        out.append(_f("erreur", f"{name} : aucun click tag (clickTag) — au moins un est obligatoire."))
    if re.search(r"\b(localStorage|sessionStorage|indexedDB|openDatabase)\b", text):
        out.append(_f("erreur", f"{name} : stockage local utilisé (localStorage, sessionStorage, "
                                "indexedDB ou openDatabase interdits)."))
    if re.search(r"""["'(]\s*http://""", text):
        out.append(_f("alerte", f"{name} : URL en http:// (SSL : toutes les URL doivent être en https)."))
    if not re.search(r"""name\s*=\s*["']ad\.size["']""", text, re.I):
        out.append(_f("alerte", f"{name} : balise <meta name=\"ad.size\"> absente "
                                "(ex. width=300,height=250)."))
    out.append(_f("alerte", f"{name} : prévoir une image de secours (backup GIF/JPG) "
                            "aux mêmes dimensions — sinon rien ne s'affiche sans HTML5."))
    return out


def check_plan(plan, creatives_dir: str = "") -> List[dict]:
    """Contrôle toutes les créatives du plan qui ont un fichier.
    Renvoie [{"creative", "file", "level", "message"}]."""
    from cm360_trafficker import resolve_creative_path
    out = []
    seen = set()
    for camp in plan.values():
        for ad in camp.ads.values():
            p0 = camp.placements.get(ad["placements"][0]) if ad["placements"] else None
            psize = (p0.width, p0.height) if p0 else None
            for c in ad["creatives"]:
                if not c.path or c.name in seen or c.ctype not in CTYPE_SPEC:
                    continue
                seen.add(c.name)
                full = resolve_creative_path(c.path, creatives_dir)
                findings = check_file(full, c.ctype, psize)
                if not findings:
                    out.append({"creative": c.name, "file": c.path, "level": "ok",
                                "message": f"{os.path.basename(c.path)} : conforme à la spec CM360."})
                for level, msg in findings:
                    out.append({"creative": c.name, "file": c.path, "level": level, "message": msg})
    return out
