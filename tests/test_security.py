"""Tests d'audit : verrouillage des routes, extraction ZIP sûre, rétention RGPD."""
import io
import os
import time
import zipfile

import pytest

pytest.importorskip("flask")
import cm360_trafficker_ui as ui
import trafficker_store as store

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PROTECTED = [("POST", "/analyze"), ("POST", "/run"), ("GET", "/bulk/x"),
             ("GET", "/adform-bulk/x"), ("POST", "/delivery/x"), ("GET", "/status/x"),
             ("GET", "/jobs"), ("GET", "/report/x"), ("GET", "/logout")]


@pytest.fixture
def auth_on(monkeypatch):
    from werkzeug.security import generate_password_hash
    monkeypatch.setenv("TRAFFICKER_PASSWORD_HASH", generate_password_hash("s3cret"))
    ui.store.clear_login_failures()
    yield
    ui.store.clear_login_failures()


@pytest.mark.parametrize("method,url", PROTECTED)
def test_every_endpoint_requires_login(auth_on, method, url):
    r = ui.app.test_client().open(url, method=method)
    assert r.status_code in (302, 401)


def test_every_route_is_covered_by_the_audit_list():
    rules = {r.rule.split("<")[0].rstrip("/") or "/" for r in ui.app.url_map.iter_rules()}
    tested = {u.rsplit("/x", 1)[0] for _, u in PROTECTED} | {"/", "/login", "/healthz", "/static"}
    assert rules <= tested, rules - tested


def test_logged_in_user_reaches_endpoints(auth_on):
    c = ui.app.test_client()
    c.post("/login", data={"user": "admin", "password": "s3cret"})
    assert c.get("/jobs").status_code == 200


# --- ZIP ------------------------------------------------------------------------

def _zip(entries, symlink=None):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries:
            z.writestr(name, data)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (0o120777 << 16)
            z.writestr(info, "/etc/passwd")
    b.seek(0)
    return zipfile.ZipFile(b)


@pytest.mark.parametrize("name", ["../evil.png", "a/../../evil.png", "/abs.png",
                                  "C:/win.png", "..\\\\evil.png"])
def test_zip_slip_rejected(tmp_path, name):
    with pytest.raises(ValueError):
        ui.safe_extract(_zip([(name, b"x")]), str(tmp_path))
    assert not any(tmp_path.parent.glob("evil.png"))


def test_symlink_rejected(tmp_path):
    with pytest.raises(ValueError):
        ui.safe_extract(_zip([], symlink="lien.png"), str(tmp_path))


def test_too_many_files_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "MAX_ZIP_FILES", 3)
    with pytest.raises(ValueError):
        ui.safe_extract(_zip([(f"f{i}.png", b"x") for i in range(4)]), str(tmp_path))


def test_zip_bomb_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "MAX_ZIP_BYTES", 1024 * 1024)
    with pytest.raises(ValueError):
        ui.safe_extract(_zip([("bombe.png", b"\0" * (5 * 1024 * 1024))]), str(tmp_path))


def test_valid_zip_extracted(tmp_path):
    ui.safe_extract(_zip([("dossier/ban.png", b"png")]), str(tmp_path))
    assert (tmp_path / "dossier" / "ban.png").read_bytes() == b"png"


def test_malicious_zip_refused_by_ui():
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("../../evil.png", b"x")
    b.seek(0)
    d = ui.app.test_client().post("/analyze", data={
        "plan": (open(os.path.join(ROOT, "plan_media_template.csv"), "rb"), "p.csv"),
        "creatives_zip": (b, "creas.zip")}, content_type="multipart/form-data").get_json()
    assert "refusé" in d["error"]


# --- Rétention RGPD -----------------------------------------------------------------

def test_retention_worker_is_running():
    assert ui._retention_started.is_set()


def test_expired_job_is_purged_and_unreadable(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "r.db"))
    old = time.time() - ui.RETENTION_SECONDS - 5
    store.save_job("vieux", {"label": "L", "created": old, "done": True, "log": ["x"]})
    store.save_job("recent", {"label": "L", "created": time.time(), "done": True, "log": ["x"]})
    c = ui.app.test_client()
    # illisible avant même la purge
    assert c.get("/status/vieux").get_json()["error"] == "job inconnu"
    assert all(j["id"] != "vieux" for j in c.get("/jobs").get_json()["jobs"])
    ui.purge_expired()
    assert store.load_job("vieux") is None and store.load_job("recent") is not None


def test_purge_runs_on_requests(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "r2.db"))
    store.save_job("vieux", {"label": "L", "created": time.time() - ui.RETENTION_SECONDS - 5,
                             "done": True, "log": []})
    ui._last_purge[0] = 0
    ui.app.test_client().get("/healthz")
    assert store.load_job("vieux") is None


def test_cf_connecting_ip_only_when_trusted(auth_on, monkeypatch):
    c = ui.app.test_client()
    h = {"CF-Connecting-IP": "9.9.9.9"}
    c.post("/login", data={"user": "admin", "password": "non"}, headers=h)
    assert store.login_failures("9.9.9.9", 300) == 0          # en-tête ignoré par défaut
    monkeypatch.setenv("TRAFFICKER_TRUST_CF", "1")
    c.post("/login", data={"user": "admin", "password": "non"}, headers=h)
    assert store.login_failures("9.9.9.9", 300) == 1
