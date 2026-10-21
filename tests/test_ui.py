import os
import time

import pytest

flask = pytest.importorskip("flask")
import cm360_trafficker_ui as ui

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _post(client, url, **extra):
    data = {"platform": "mock", "demo": "on", **extra}
    data["plan"] = (open(os.path.join(ROOT, "plan_media_template.csv"), "rb"), "plan.csv")
    return client.post(url, data=data, content_type="multipart/form-data")


def test_full_demo_flow_with_delivery_report():
    c = ui.app.test_client()
    assert c.get("/").status_code == 200
    j = _post(c, "/analyze").get_json()
    assert j["errors"] == []
    run = c.post("/run", data={"token": j["token"]}, content_type="multipart/form-data").get_json()
    jid = run["job_id"]
    for _ in range(40):
        s = c.get(f"/status/{jid}").get_json()
        if s["done"]:
            break
        time.sleep(0.25)
    assert s["done"] and not s["error"]
    assert c.get(f"/report/{jid}").status_code == 200
    d = c.post(f"/delivery/{jid}").get_json()
    assert "error" not in d
    assert "BN_Home_300x250" in d["html"] and "€" in d["html"]


def test_delivery_unknown_job():
    assert "error" in ui.app.test_client().post("/delivery/inconnu").get_json()


def test_jobs_persist_across_restart(tmp_path, monkeypatch):
    import trafficker_store as store
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "t.db"))
    c = ui.app.test_client()
    j = _post(c, "/analyze").get_json()
    jid = c.post("/run", data={"token": j["token"]}, content_type="multipart/form-data").get_json()["job_id"]
    for _ in range(40):
        if c.get(f"/status/{jid}").get_json()["done"]:
            break
        time.sleep(0.25)
    ui.JOBS.clear()                                  # simule un redémarrage
    s = c.get(f"/status/{jid}").get_json()
    assert s["done"] and not s["error"] and s["log"]
    assert any(x["id"] == jid for x in c.get("/jobs").get_json()["jobs"])
    assert c.get(f"/report/{jid}").status_code == 200
    assert "error" not in c.post(f"/delivery/{jid}").get_json()
    store.purge(-1)                                  # RGPD : tout est purgé
    assert store.load_job(jid) is None


def test_auth(monkeypatch):
    from werkzeug.security import generate_password_hash
    monkeypatch.setenv("TRAFFICKER_PASSWORD_HASH", generate_password_hash("s3cret"))
    ui.store.clear_login_failures()
    c = ui.app.test_client()
    assert c.get("/").status_code == 302                      # redirigé vers /login
    assert c.post("/analyze").status_code == 401              # API fermée
    assert c.post("/login", data={"user": "admin", "password": "non"}).status_code == 401
    assert c.post("/login", data={"user": "admin", "password": "s3cret"}).status_code == 302
    assert c.get("/").status_code == 200
    c.get("/logout")
    assert c.get("/").status_code == 302


def test_login_rate_limit(monkeypatch):
    from werkzeug.security import generate_password_hash
    monkeypatch.setenv("TRAFFICKER_PASSWORD_HASH", generate_password_hash("s3cret"))
    ui.store.clear_login_failures()
    c = ui.app.test_client()
    codes = [c.post("/login", data={"user": "admin", "password": "x"}).status_code
             for _ in range(7)]
    assert codes[:5] == [401] * 5 and codes[5:] == [429, 429]
    ui.store.clear_login_failures()


def test_bulk_download_from_analysis():
    pytest.importorskip("openpyxl")
    c = ui.app.test_client()
    j = _post(c, "/analyze").get_json()
    r = c.get(f"/bulk/{j['token']}")
    assert r.status_code == 200 and r.data[:2] == b"PK"      # xlsx = zip
    assert c.get("/bulk/inconnu").status_code == 404


def test_healthz_open_even_with_auth(monkeypatch):
    from werkzeug.security import generate_password_hash
    monkeypatch.setenv("TRAFFICKER_PASSWORD_HASH", generate_password_hash("x"))
    assert ui.app.test_client().get("/healthz").get_json() == {"ok": True}
