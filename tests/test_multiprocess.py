"""État partagé en SQLite : l'UI fonctionne avec plusieurs processus (gunicorn -w N)."""
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import uuid

import pytest

pytest.importorskip("flask")
import cm360_trafficker_ui as ui
import trafficker_store as store

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLAN = os.path.join(ROOT, "plan_media_template.csv")


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "mp.db"))
    return tmp_path / "mp.db"


def _analyze(c, **extra):
    data = {"platform": "mock", "demo": "on", **extra,
            "plan": (open(PLAN, "rb"), "plan.csv")}
    return c.post("/analyze", data=data, content_type="multipart/form-data").get_json()


def test_plan_survives_other_process(db):
    c = ui.app.test_client()
    tok = _analyze(c)["token"]
    ui.JOBS.clear()                         # « autre processus » : aucune mémoire partagée
    assert c.get(f"/bulk/{tok}").status_code == 200
    jid = c.post("/run", data={"token": tok}).get_json()["job_id"]
    for _ in range(40):
        ui.JOBS.clear()                     # le statut est relu depuis la base
        s = c.get(f"/status/{jid}").get_json()
        if s["done"]:
            break
        time.sleep(0.25)
    assert s["done"] and not s["error"] and s["log"]


def test_plan_can_only_be_launched_once(db):
    c = ui.app.test_client()
    tok = _analyze(c)["token"]
    assert "job_id" in c.post("/run", data={"token": tok}).get_json()
    assert "error" in c.post("/run", data={"token": tok}).get_json()


def test_take_plan_is_exclusive(db):
    store.save_plan("t", {"plan": {}, "created": time.time()})
    assert store.take_plan("t") is not None and store.take_plan("t") is None


def test_secrets_never_written_to_db(db):
    c = ui.app.test_client()
    secret = "SECRET-" + uuid.uuid4().hex
    tok = _analyze(c, adform_client_secret=secret, service_account="/cle-" + secret)["token"]
    c.post("/run", data={"token": tok, "adform_client_secret": secret})
    time.sleep(0.5)
    for f in db.parent.glob("mp.db*"):          # base + journal WAL
        assert secret.encode() not in f.read_bytes()


def test_login_failures_shared(db):
    store.clear_login_failures()
    for _ in range(3):
        store.add_login_failure("1.2.3.4")
    assert store.login_failures("1.2.3.4", 300) == 3
    assert store.login_failures("5.6.7.8", 300) == 0


def test_purge_removes_plans_and_their_creatives(db, tmp_path):
    d = tmp_path / "creas"
    d.mkdir()
    store.save_plan("vieux", {"plan": {}, "creatives_dir": str(d),
                              "created": time.time() - ui.RETENTION_SECONDS - 5})
    ui.purge_expired()
    assert store.load_plan("vieux") is None and not d.exists()


# --- Vrai serveur multi-processus ---------------------------------------------------

def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _multipart(fields, file_field, path):
    b = uuid.uuid4().hex
    out = []
    for k, v in fields.items():
        out.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    out.append(f'--{b}\r\nContent-Disposition: form-data; name="{file_field}"; filename="p.csv"\r\n'
               f'Content-Type: text/csv\r\n\r\n'.encode() + open(path, "rb").read() + b"\r\n")
    out.append(f"--{b}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={b}"


def test_gunicorn_three_workers(tmp_path):
    gunicorn = shutil.which("gunicorn") or os.path.join(os.path.dirname(sys.executable), "gunicorn")
    if not os.path.exists(gunicorn):
        pytest.skip("gunicorn absent")
    port = _free_port()
    env = dict(os.environ, TRAFFICKER_DB=str(tmp_path / "g.db"), TMPDIR=str(tmp_path))
    env.pop("TRAFFICKER_PASSWORD_HASH", None)
    p = subprocess.Popen([gunicorn, "-w", "3", "--threads", "2", "-b", f"127.0.0.1:{port}",
                          "cm360_trafficker_ui:app"], cwd=ROOT, env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(base + "/healthz", timeout=1)
                break
            except OSError:
                time.sleep(0.2)
        body, ctype = _multipart({"platform": "mock", "demo": "on"}, "plan", PLAN)
        req = urllib.request.Request(base + "/analyze", data=body, headers={"Content-Type": ctype})
        tok = json.load(urllib.request.urlopen(req))["token"]
        # le jeton est utilisable quel que soit le processus qui reçoit la requête
        for _ in range(6):
            assert urllib.request.urlopen(f"{base}/bulk/{tok}").status == 200
        req = urllib.request.Request(base + "/run", data=f"token={tok}".encode(),
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        jid = json.load(urllib.request.urlopen(req))["job_id"]
        for _ in range(60):
            s = json.load(urllib.request.urlopen(f"{base}/status/{jid}"))
            if s["done"]:
                break
            time.sleep(0.25)
        assert s["done"] and not s["error"], s
        jobs = [json.load(urllib.request.urlopen(f"{base}/jobs"))["jobs"] for _ in range(6)]
        assert all(any(j["id"] == jid for j in js) for js in jobs)
    finally:
        p.terminate()
        p.wait(timeout=10)
