"""Contrôle des créatives selon la base de specs CM360 (specs/cm360_creative_specs.json)."""
import io
import struct
import zipfile
import zlib

import pytest

import creative_specs as cs
from cm360_trafficker import resolve_creative_type


def png(w, h):
    raw = b"".join(b"\x00" + b"\x00\x00\x00" * w for _ in range(h))
    def chunk(k, d):
        return struct.pack(">I", len(d)) + k + d + struct.pack(">I", zlib.crc32(k + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def mp4(duration_s, w, h, codec=b"avc1"):
    def box(k, d):
        return struct.pack(">I", 8 + len(d)) + k + d
    mvhd = box(b"mvhd", b"\x00\x00\x00\x00" + b"\x00" * 8 + struct.pack(">II", 1000, int(duration_s * 1000)) + b"\x00" * 80)
    tkhd = box(b"tkhd", b"\x00\x00\x00\x00" + b"\x00" * 72 + struct.pack(">II", w << 16, h << 16))
    stsd = box(b"stsd", b"\x00" * 8 + box(codec, b"\x00" * 70))
    return box(b"ftyp", b"isom") + box(b"moov", mvhd + box(b"trak", tkhd + stsd))


def html5_zip(html, extra=()):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("index.html", html)
        for name, data in extra:
            z.writestr(name, data)
    return b.getvalue()


GOOD_HTML = ('<meta name="ad.size" content="width=300,height=250">'
             '<script>var clickTag="https://x.fr";</script>')


def _write(tmp_path, name, data):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


def test_specs_base_loaded():
    ids = {s["Identifiant"] for s in cs.load_specs()}
    assert len(ids) == 12 and set(cs.CTYPE_SPEC.values()) <= ids


@pytest.mark.parametrize("path,ctype", [("a.zip", "HTML5"), ("a.adz", "HTML5"), ("a.mp3", "AUDIO"),
                                        ("a.wbmp", "IMAGE"), ("a.m4v", "VIDEO")])
def test_new_types_from_specs(path, ctype):
    assert resolve_creative_type("", "", "", path)[0] == ctype


def test_image_ok_and_ratio_alert(tmp_path):
    assert cs.check_file(_write(tmp_path, "ok.png", png(600, 500)), "IMAGE", (300, 250)) == []
    alerts = cs.check_file(_write(tmp_path, "ratio.png", png(300, 300)), "IMAGE", (300, 250))
    assert alerts and "ratio" in alerts[0][1]


def test_image_wrong_extension_and_weight(tmp_path, monkeypatch):
    monkeypatch.setitem(cs.RULES["Display – multidevice – Image"], "max_bytes", 100)
    f = cs.check_file(_write(tmp_path, "big.png", png(300, 250)), "IMAGE", (300, 250))
    assert any(level == "erreur" and "Mo" in m for level, m in f)
    f = cs.check_file(_write(tmp_path, "x.bmp", b"BM"), "IMAGE")
    assert any("extension .bmp refusée" in m for _, m in f)


def test_video_duration_size_codec(tmp_path):
    assert cs.check_file(_write(tmp_path, "ok.mp4", mp4(15, 1920, 1080)), "VIDEO") == []
    msgs = " ".join(m for _, m in cs.check_file(_write(tmp_path, "ko.mp4", mp4(22, 640, 480, b"hvc1")), "VIDEO"))
    assert "22.0 s" in msgs and "640×480" in msgs and "hvc1" in msgs
    # 14,6 s -> arrondi à 15 s : conforme
    assert cs.check_file(_write(tmp_path, "r.mp4", mp4(14.6, 1280, 720)), "VIDEO") == []


def test_html5_rules(tmp_path):
    ok = cs.check_file(_write(tmp_path, "ok.zip", html5_zip(GOOD_HTML, [("img/a.png", b"x")])), "HTML5")
    assert [lvl for lvl, _ in ok] == ["alerte"]                    # seul rappel : image de secours
    bad = cs.check_file(_write(tmp_path, "ko.zip", html5_zip(
        "<script>localStorage.x=1; var u='http://x.fr'</script>",
        [("a%20b.png", b"x"), ("inner.zip", b"x"), ("film.exe", b"x")])), "HTML5")
    text = " ".join(m for _, m in bad)
    for expected in ("click tag", "stockage local", "contient un %", ".zip imbriqué",
                     "non autorisé « film.exe »", "http://", "ad.size"):
        assert expected in text, expected


def test_html5_too_many_files(tmp_path):
    files = [(f"f{i}.png", b"x") for i in range(101)]
    f = cs.check_file(_write(tmp_path, "many.zip", html5_zip(GOOD_HTML, files)), "HTML5")
    assert any(level == "erreur" and "100 maximum" in m for level, m in f)


def test_missing_file_is_a_warning_not_a_block(tmp_path):
    f = cs.check_file(str(tmp_path / "absent.png"), "IMAGE")
    assert f[0][0] == "alerte" and "non fourni" in f[0][1]


def test_check_plan_reports_per_creative(tmp_path):
    from cm360_trafficker import plan_from_rows
    (tmp_path / "ban.png").write_bytes(png(600, 500))
    rows = [{"campaign_name": "C", "campaign_start": "2026-11-02", "campaign_end": "2026-12-15",
             "placement_name": "P", "size": "300x250", "ad_name": "A", "creative_name": "K",
             "creative_path": "ban.png", "landing_page_url": "https://x.fr"}]
    plan, errors = plan_from_rows(rows)
    assert errors == []
    res = cs.check_plan(plan, str(tmp_path))
    assert res == [{"creative": "K", "file": "ban.png", "level": "ok",
                    "message": "ban.png : conforme à la spec CM360."}]
