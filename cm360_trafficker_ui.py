
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cm360_trafficker_ui.py
======================
Interface conversationnelle (style ChatGPT) pour le moteur cm360_trafficker.py :
l'utilisateur colle l'URL d'un Google Sheet ou joint son plan média (📎), l'assistant
vérifie le plan, applique les nomenclatures de nommage de l'annonceur, montre l'aperçu,
puis exécute le trafficking après validation — logs en direct dans la conversation et
rapport JSON téléchargeable.

Réglages (⚙️) : plateforme cible (CM360 / Adform / mode démo), clé de compte de service,
identifiants Adform. Sidebar : exécutions récentes (rejouer logs / rapport).

Conformité RGPD intégrée : minimisation, purge automatique (créatives dès la fin du
job, jobs et rapports au plus tard 1 h après), secrets jamais journalisés.

À placer dans le même dossier que cm360_trafficker.py, puis :
    pip install flask google-api-python-client google-auth openpyxl
    python cm360_trafficker_ui.py
    -> http://localhost:5000
"""

import html as _html
import json
import os
import shutil
import threading
import time
import traceback
import uuid
import zipfile
from collections import defaultdict

from flask import Flask, jsonify, redirect, request, session
from werkzeug.security import check_password_hash

import trafficker_store as store

from cm360_trafficker import (
    apply_nomenclature,
    build_adapter,
    load_nomenclature,
    load_rows_from_source,
    plan_from_rows,
    traffic_plan,
)
from cm360_reporting import (
    build_reporting_adapter,
    delivery_to_dict,
    report_for_plan,
)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 Mo

# RGPD : durée maximale de conservation des jobs et plans (rapports inclus)
RETENTION_SECONDS = 3600  # 1 heure

# Jobs : job_id -> {"log", "done", "report", "error", "created", "label"}
JOBS: dict = {}
# Plans analysés en attente d'exécution : token -> paramètres
PLANS: dict = {}

# ---------------------------------------------------------------------------
# Authentification (optionnelle)
# ---------------------------------------------------------------------------
# Activée si TRAFFICKER_PASSWORD_HASH est défini (hash werkzeug du mot de passe,
# voir le guide). TRAFFICKER_USER (défaut « admin ») et TRAFFICKER_SECRET_KEY
# (clé de session ; aléatoire à chaque démarrage si absente) complètent.
# Sans hash, l'UI reste ouverte : à n'utiliser qu'en local (127.0.0.1).

app.secret_key = os.environ.get("TRAFFICKER_SECRET_KEY") or uuid.uuid4().hex
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
LOGIN_ATTEMPTS: dict = defaultdict(list)   # ip -> horodatages des échecs
MAX_ATTEMPTS, ATTEMPT_WINDOW = 5, 300


def _auth_enabled() -> bool:
    return bool(os.environ.get("TRAFFICKER_PASSWORD_HASH"))


LOGIN_PAGE = """<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Trafficker — connexion</title>
<style>body{font-family:system-ui,sans-serif;background:#f4f4f4;display:flex;min-height:100vh;
align-items:center;justify-content:center;margin:0}form{background:#fff;padding:28px;border-radius:16px;
width:300px;box-shadow:0 2px 12px #0002}input{width:100%;box-sizing:border-box;padding:9px;margin:6px 0 14px;
border:1px solid #ccc;border-radius:8px}button{width:100%;padding:10px;border:0;border-radius:8px;
background:#1a73e8;color:#fff;font-weight:600;cursor:pointer}.err{color:#b00020}</style></head><body>
<form method="post" action="/login"><h2>Trafficker</h2>__ERR__
<label>Utilisateur<input name="user" autocomplete="username" required></label>
<label>Mot de passe<input name="password" type="password" autocomplete="current-password" required></label>
<button>Se connecter</button></form></body></html>"""


@app.before_request
def _require_login():
    if not _auth_enabled() or request.endpoint in ("login", "static"):
        return None
    if session.get("user"):
        return None
    if request.method == "GET" and request.path == "/":
        return redirect("/login")
    return jsonify({"error": "Authentification requise."}), 401


@app.route("/login", methods=["GET", "POST"])
def login():
    if not _auth_enabled():
        return redirect("/")
    if request.method == "GET":
        return LOGIN_PAGE.replace("__ERR__", "")
    ip = request.remote_addr or "?"
    now = time.time()
    LOGIN_ATTEMPTS[ip] = [t for t in LOGIN_ATTEMPTS[ip] if now - t < ATTEMPT_WINDOW]
    if len(LOGIN_ATTEMPTS[ip]) >= MAX_ATTEMPTS:
        return (LOGIN_PAGE.replace("__ERR__", "<p class='err'>Trop d'essais, réessayez dans 5 minutes.</p>"), 429)
    ok_user = request.form.get("user", "") == os.environ.get("TRAFFICKER_USER", "admin")
    ok_pwd = check_password_hash(os.environ["TRAFFICKER_PASSWORD_HASH"],
                                 request.form.get("password", ""))
    if ok_user and ok_pwd:
        session["user"] = request.form["user"]
        LOGIN_ATTEMPTS.pop(ip, None)
        return redirect("/")
    LOGIN_ATTEMPTS[ip].append(now)
    return (LOGIN_PAGE.replace("__ERR__", "<p class='err'>Identifiants incorrects.</p>"), 401)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# ---------------------------------------------------------------------------
# Page conversationnelle (client)
# ---------------------------------------------------------------------------

PAGE = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Trafficker</title>
<style>
:root { --bg:#ffffff; --sidebar:#f9f9f9; --border:#e5e5e5; --text:#1a1a1a;
        --muted:#8f8f8f; --accent:#10a37f; --user:#f4f4f4; }
* { box-sizing:border-box; margin:0; }
body { font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
       background:var(--bg); color:var(--text); }
.sidebar { position:fixed; top:0; bottom:0; left:0; width:260px; background:var(--sidebar);
            border-right:1px solid var(--border); padding:10px; display:flex;
            flex-direction:column; gap:8px; }
.new-btn { display:flex; gap:8px; align-items:center; padding:10px 12px; border-radius:10px;
           cursor:pointer; font-size:.95rem; background:#fff; border:1px solid var(--border); }
.new-btn:hover { background:#f0f0f0; }
.sb-title { font-size:.72rem; color:var(--muted); padding:12px 10px 2px;
            text-transform:uppercase; letter-spacing:.05em; }
#job-list { overflow-y:auto; }
.job-item { padding:9px 10px; border-radius:10px; cursor:pointer; font-size:.88rem;
            white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.job-item:hover { background:#ececec; }
.main { margin-left:260px; min-height:100vh; display:flex; flex-direction:column; }
.chat { flex:1; width:100%; max-width:48rem; margin:0 auto; padding:24px 16px 170px; }
.msg { margin:18px 0; display:flex; gap:12px; line-height:1.6; }
.msg.user { justify-content:flex-end; }
.msg.user .bubble { background:var(--user); padding:10px 16px; border-radius:18px;
                    max-width:80%; white-space:pre-wrap; }
.ava { width:28px; height:28px; border-radius:50%; background:var(--accent); color:#fff;
       display:flex; align-items:center; justify-content:center; font-size:.8rem; flex:none; }
.body { flex:1; min-width:0; }
.body p { margin:.4rem 0; }
.card { background:#f7f7f8; border:1px solid var(--border); border-radius:12px;
        padding:12px 14px; margin:.6rem 0; }
.err { color:#c0392b; }
pre.log { background:#101828; color:#d6eaf8; padding:12px; border-radius:12px;
          overflow-x:auto; max-height:340px; font-size:.8rem; white-space:pre-wrap; }
table { border-collapse:collapse; width:100%; margin-top:6px; }
td, th { border:1px solid var(--border); padding:4px 6px; font-size:.85rem; text-align:left; }
th { background:#eef2fb; }
.btn { display:inline-block; padding:9px 18px; background:var(--accent); color:#fff;
       border:0; border-radius:10px; cursor:pointer; font-size:.95rem; margin-top:6px;
       text-decoration:none; }
.btn:hover { filter:brightness(.93); }
.btn:disabled { opacity:.5; }
.composer { position:fixed; bottom:0; left:260px; right:0; padding:0 16px 18px;
            background:linear-gradient(transparent, var(--bg) 30%); }
.composer-inner { max-width:48rem; margin:0 auto; position:relative; }
.settings { display:none; background:#f9f9f9; border:1px solid var(--border); border-radius:16px;
            padding:14px; margin-bottom:8px; font-size:.9rem; }
.settings label { display:block; margin-top:8px; font-weight:600; font-size:.8rem; }
.settings input, .settings select { width:100%; padding:7px 10px; border:1px solid var(--border);
                                    border-radius:8px; font:inherit; }
.settings label.ck { display:flex; gap:8px; align-items:center; margin-top:12px; font-weight:600; }
.settings label.ck input { width:auto; }
.box { border:1px solid var(--border); border-radius:24px; background:#fff; padding:10px 12px;
       box-shadow:0 2px 12px rgba(0,0,0,.04); }
.chips { display:flex; flex-wrap:wrap; gap:6px; margin-bottom:6px; }
.chip { background:#eef2fb; border-radius:8px; padding:3px 9px; font-size:.8rem;
        display:flex; gap:6px; align-items:center; }
.chip button { border:0; background:none; cursor:pointer; color:#666; }
textarea { width:100%; border:0; resize:none; font:inherit; outline:none; max-height:180px; }
.row { display:flex; align-items:flex-end; gap:8px; }
.icon-btn { border:0; background:none; cursor:pointer; font-size:1.05rem; padding:4px;
            border-radius:50%; color:#555; }
.icon-btn:hover { background:#f0f0f0; }
.send { width:32px; height:32px; border-radius:50%; border:0; background:var(--text);
       color:#fff; cursor:pointer; font-size:1rem; flex:none; }
.menu { position:absolute; bottom:64px; left:0; background:#fff; border:1px solid var(--border);
        border-radius:12px; box-shadow:0 4px 16px rgba(0,0,0,.08); padding:6px; display:none; z-index:5; }
.menu button { display:block; width:100%; text-align:left; background:none; border:0;
               padding:9px 12px; border-radius:8px; cursor:pointer; font-size:.9rem; }
.menu button:hover { background:#f4f4f4; }
.hint { text-align:center; color:var(--muted); font-size:.72rem; margin-top:8px; }
.dots { animation:blink 1s infinite; }
@keyframes blink { 50% { opacity:.3; } }
@media (max-width:760px){ .sidebar{display:none} .main{margin-left:0} .composer{left:0} }
</style>
</head>
<body>
<aside class="sidebar">
  <div class="new-btn" onclick="newChat()">＋ Nouveau trafficking</div>
  <div class="sb-title">Exécutions récentes</div>
  <div id="job-list"></div>
</aside>
<div class="main">
  <div class="chat" id="chat"></div>
  <div class="composer">
    <div class="composer-inner">
      <div class="settings" id="settings">
        <label>Plateforme cible</label>
        <select id="platform">
          <option value="cm360">Campaign Manager 360 (réel)</option>
          <option value="adform">Adform (réel)</option>
        </select>
        <label class="ck"><input type="checkbox" id="demo"> Mode démo — plateforme simulée (aucun accès requis)</label>
        <label>Clé du compte de service Google (CM360) — chemin du fichier .json</label>
        <input id="service_account" placeholder="/chemin/vers/cm360-sa.json" autocomplete="off">
        <label>ID du profil CM360 (optionnel)</label>
        <input id="profile_id" placeholder="ex. 1234567">
        <label>Adform — Client ID OAuth</label>
        <input id="adform_client_id" autocomplete="off">
        <label>Adform — Client secret OAuth</label>
        <input type="password" id="adform_client_secret" autocomplete="off">
      </div>
      <div class="box">
        <div class="chips" id="chips"></div>
        <div class="row">
          <button class="icon-btn" id="attach" title="Joindre des fichiers">📎</button>
          <button class="icon-btn" id="gear" title="Réglages plateforme">⚙️</button>
          <textarea id="input" rows="1"
            placeholder="Collez l'URL d'un Google Sheet partagé, ou joignez votre plan média…"></textarea>
          <button class="send" id="send" title="Envoyer">↑</button>
        </div>
      </div>
      <div class="menu" id="menu">
        <button onclick="pick('plan')">📄 Plan média (.csv / .xlsx)</button>
        <button onclick="pick('nomen')">🏷️ Nomenclatures de nommage (JSON)</button>
        <button onclick="pick('zip')">🖼️ Créatives IMAGE (ZIP)</button>
      </div>
      <div class="hint">Fichiers purgés automatiquement après traitement (RGPD). Entrée pour envoyer, Maj+Entrée pour un retour à la ligne.</div>
    </div>
  </div>
</div>
<input type="file" id="f-plan" accept=".csv,.xlsx" hidden>
<input type="file" id="f-nomen" accept=".json" hidden>
<input type="file" id="f-zip" accept=".zip" hidden>
<script>
const chat = document.getElementById('chat');
const input = document.getElementById('input');
const menu = document.getElementById('menu');
let files = {plan: null, nomen: null, zip: null};
let busy = false;

function esc(s){ return String(s).replace(/[&<>"]/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

function addMsg(role, html){
  const m = document.createElement('div');
  m.className = 'msg ' + (role === 'user' ? 'user' : 'bot');
  if (role === 'user') {
    const b = document.createElement('div'); b.className = 'bubble';
    b.innerHTML = html; m.appendChild(b);
  } else {
    const a = document.createElement('div'); a.className = 'ava'; a.textContent = 'T';
    const b = document.createElement('div'); b.className = 'body'; b.innerHTML = html;
    m.append(a, b);
  }
  chat.appendChild(m); chat.scrollTop = chat.scrollHeight;
  return m;
}

function greeting(){
  addMsg('bot',
    "<p>Bonjour 👋 Je génère le trafficking de vos campagnes à partir d'un plan média.</p>" +
    "<p><b>Comment démarrer :</b><br>" +
    "• Joignez votre plan média (.csv / .xlsx) ou collez l'URL d'un Google Sheet partagé<br>" +
    "• En option : nomenclatures de nommage (JSON), ZIP de créatives<br>" +
    "• Réglages ⚙️ : plateforme cible (CM360 / Adform), mode démo, identifiants</p>" +
    "<p>Je vérifie le plan, j'applique vos nomenclatures de nommage, puis je crée " +
    "tout sur l'ad server — seulement après votre validation.</p>");
}

function renderChips(){
  const c = document.getElementById('chips'); c.innerHTML = '';
  const icons = {plan: '📄', nomen: '🏷️', zip: '🖼️'};
  for (const k of ['plan', 'nomen', 'zip']) if (files[k]) {
    const chip = document.createElement('span'); chip.className = 'chip';
    chip.innerHTML = icons[k] + ' ' + esc(files[k].name) + ' <button>✕</button>';
    chip.querySelector('button').onclick = () => { files[k] = null; renderChips(); };
    c.appendChild(chip);
  }
}

function pick(kind){
  menu.style.display = 'none';
  const el = document.getElementById('f-' + kind);
  el.value = ''; el.click();
  el.onchange = () => { files[kind] = el.files[0] || null; renderChips(); };
}

async function send(){
  if (busy) return;
  const txt = input.value.trim();
  if (!txt && !files.plan && !files.nomen && !files.zip) return;
  busy = true;
  let u = txt ? esc(txt) : '';
  for (const [k, ic] of [['plan', '📄'], ['nomen', '🏷️'], ['zip', '🖼️']])
    if (files[k]) u += (u ? '<br>' : '') + ic + ' ' + esc(files[k].name);
  addMsg('user', u);
  const t = addMsg('bot', '<span class="dots">…</span>');
  const fd = new FormData();
  if (txt) fd.append('sheet_url', txt);
  if (files.plan) fd.append('plan', files.plan);
  if (files.nomen) fd.append('nomenclature', files.nomen);
  if (files.zip) fd.append('creatives_zip', files.zip);
  fd.append('platform', document.getElementById('platform').value);
  fd.append('service_account', document.getElementById('service_account').value);
  fd.append('profile_id', document.getElementById('profile_id').value);
  fd.append('adform_client_id', document.getElementById('adform_client_id').value);
  fd.append('adform_client_secret', document.getElementById('adform_client_secret').value);
  fd.append('demo', document.getElementById('demo').checked ? 'on' : '');
  input.value = ''; input.style.height = 'auto';
  files = {plan: null, nomen: null, zip: null}; renderChips();
  try {
    const r = await fetch('/analyze', {method: 'POST', body: fd});
    const d = await r.json();
    t.querySelector('.body').innerHTML =
      d.error ? '<p class="err">' + esc(d.error) + '</p>' : d.html;
  } catch (e) {
    t.querySelector('.body').innerHTML =
      '<p class="err">Erreur réseau : ' + esc(String(e)) + '</p>';
  }
  chat.scrollTop = chat.scrollHeight;
  busy = false;
}

async function launch(btn, token){
  if (busy) return;
  busy = true;
  btn.disabled = true; btn.textContent = 'Lancement…';
  const fd = new FormData(); fd.append('token', token);
  try {
    const d = await (await fetch('/run', {method: 'POST', body: fd})).json();
    if (d.error) { btn.outerHTML = '<p class="err">' + esc(d.error) + '</p>'; busy = false; return; }
    const m = addMsg('bot', '<p>Trafficking en cours…</p><pre class="log"></pre>');
    const logEl = m.querySelector('pre');
    while (true) {
      await new Promise(res => setTimeout(res, 1000));
      const s = await (await fetch('/status/' + d.job_id)).json();
      logEl.textContent = s.log.join('\\n');
      chat.scrollTop = chat.scrollHeight;
      if (s.done) {
        m.querySelector('.body').insertAdjacentHTML('beforeend',
          s.error ? '<p class="err">Échec : ' + esc(s.error) + '</p>'
                  : '<p><b>Terminé.</b></p><a class="btn" href="/report/' +
                    d.job_id + '">⬇ Télécharger le rapport JSON</a> ' +
                    '<button class="btn" onclick="showDelivery(this, \\'' + d.job_id +
                    '\\')">📊 Rapport de diffusion</button>');
        break;
      }
    }
    refreshJobs();
  } catch (e) {
    btn.outerHTML = '<p class="err">Erreur : ' + esc(String(e)) + '</p>';
  }
  busy = false;
}

async function refreshJobs(){
  try {
    const d = await (await fetch('/jobs')).json();
    const el = document.getElementById('job-list'); el.innerHTML = '';
    for (const j of d.jobs) {
      const it = document.createElement('div'); it.className = 'job-item';
      it.textContent = (j.done && !j.error ? '✅ ' : (j.error ? '❌ ' : '⏳ ')) + j.label;
      it.title = 'Voir les logs';
      it.onclick = () => showJob(j.id);
      el.appendChild(it);
    }
  } catch (e) { /* ignore */ }
}

async function showJob(id){
  const s = await (await fetch('/status/' + id)).json();
  let html = '<p>Exécution :</p><pre class="log">' + esc(s.log.join('\\n')) + '</pre>';
  if (s.done) html += s.error
    ? '<p class="err">Échec : ' + esc(s.error) + '</p>'
    : '<a class="btn" href="/report/' + id + '">⬇ Rapport JSON</a> ' +
      '<button class="btn" onclick="showDelivery(this, \\'' + id + '\\')">📊 Rapport de diffusion</button>';
  addMsg('bot', html);
}

async function showDelivery(btn, id){
  btn.disabled = true; btn.textContent = 'Chargement…';
  const t = addMsg('bot', '<span class="dots">…</span>');
  try {
    const d = await (await fetch('/delivery/' + id, {method: 'POST'})).json();
    t.querySelector('.body').innerHTML =
      d.error ? '<p class="err">' + esc(d.error) + '</p>' : d.html;
  } catch (e) {
    t.querySelector('.body').innerHTML = '<p class="err">Erreur réseau : ' + esc(String(e)) + '</p>';
  }
  btn.disabled = false; btn.textContent = '📊 Rapport de diffusion';
  chat.scrollTop = chat.scrollHeight;
}

function newChat(){ chat.innerHTML = ''; greeting(); }

document.getElementById('send').onclick = send;
input.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
});
input.addEventListener('input', () => {
  input.style.height = 'auto'; input.style.height = input.scrollHeight + 'px';
});
document.getElementById('attach').onclick = e => {
  e.stopPropagation();
  menu.style.display = menu.style.display === 'block' ? 'none' : 'block';
};
document.getElementById('gear').onclick = () => {
  const s = document.getElementById('settings');
  s.style.display = s.style.display === 'block' ? 'none' : 'block';
};
document.addEventListener('click', () => { menu.style.display = 'none'; });

greeting();
refreshJobs();
</script>
</body></html>
"""


@app.route("/", methods=["GET"])
def home():
    return PAGE


# ---------------------------------------------------------------------------
# Analyse du plan (étape de vérification, avant envoi)
# ---------------------------------------------------------------------------

def _preview_html(rows, plan, errors, renames, token):
    parts = [f"<p><b>{len(rows)}</b> ligne(s) lues, "
             f"<b>{len(plan)}</b> campagne(s), "
             f"<b>{len(errors)}</b> erreur(s).</p>"]
    if renames:
        parts.append("<div class='card'><b>Nomenclatures de nommage appliquées "
                     f"({len(renames)} renommage(s)) :</b><ul>"
                     + "".join(f"<li>{r}</li>" for r in renames)
                     + "</ul></div>")
    for camp in plan.values():
        rows_html = ""
        for ad_name, ad in camp.ads.items():
            rows_html += (f"<tr><td>{ad_name}</td>"
                         f"<td>{', '.join(ad['placements'])}</td>"
                         f"<td>{', '.join(c.name + ' (' + c.ctype + ')' for c in ad['creatives'])}</td>"
                         f"<td>{ad['landing_page_url']}</td></tr>")
        parts.append(
            f"<div class='card'><b>Campagne :</b> {camp.name} "
            f"({camp.start} → {camp.end}) — {len(camp.placements)} placement(s)<br>"
            f"<b>Annonceur :</b> {camp.advertiser_id or camp.advertiser_name or '?'}<br>"
            "<table><tr><th>Annonce</th><th>Placements</th><th>Créatives</th>"
            "<th>URL de destination</th></tr>" + rows_html + "</table></div>")
    if errors:
        parts.append("<div class='card err'><b>Erreurs à corriger :</b><ul>" +
                     "".join(f"<li>{e}</li>" for e in errors) + "</ul></div>")
    if token:
        parts.append(f"<p><button class='btn' onclick=\"launch(this, '{token}')\">"
                     "🚀 Lancer le trafficking</button></p>")
    return "".join(parts)


@app.route("/analyze", methods=["POST"])
def analyze():
    f = request.files.get("plan")
    sheet_url = (request.form.get("sheet_url") or "").strip()
    if not ((f and f.filename) or sheet_url):
        return jsonify({"error": "Joignez un plan média (.csv/.xlsx) ou collez "
                                 "l'URL d'un Google Sheet partagé en lecture."})

    # ZIP de créatives : décompression dans un dossier temporaire
    creatives_dir = ""
    zipf = request.files.get("creatives_zip")
    if zipf and zipf.filename:
        creatives_dir = os.path.join(os.environ.get("TMPDIR", "/tmp"),
                                     "creas_" + uuid.uuid4().hex)
        os.makedirs(creatives_dir, exist_ok=True)
        zpath = os.path.join(creatives_dir, "bundle.zip")
        zipf.save(zpath)
        try:
            with zipfile.ZipFile(zpath) as z:
                z.extractall(creatives_dir)
        except zipfile.BadZipFile:
            shutil.rmtree(creatives_dir, ignore_errors=True)
            return jsonify({"error": "ZIP de créatives invalide."})
        os.remove(zpath)

    renames: list = []
    try:
        if f and f.filename:
            suffix = os.path.splitext(f.filename)[1].lower()
            tmp = os.path.join(os.environ.get("TMPDIR", "/tmp"),
                               "plan_" + uuid.uuid4().hex + suffix)
            f.save(tmp)
            try:
                rows = load_rows_from_source(tmp)
            finally:
                os.remove(tmp)
        else:
            rows = load_rows_from_source(sheet_url)
        plan, errors = plan_from_rows(rows)

        # Couche de modification avant envoi : nomenclatures de l'annonceur
        nf = request.files.get("nomenclature")
        if nf and nf.filename:
            tmpn = os.path.join(os.environ.get("TMPDIR", "/tmp"),
                                "nomen_" + uuid.uuid4().hex + ".json")
            nf.save(tmpn)
            try:
                naming = load_nomenclature(tmpn)
            finally:
                os.remove(tmpn)  # RGPD : purge immédiate du fichier
            if naming:
                plan, renames = apply_nomenclature(plan, naming)
    except SystemExit as e:
        shutil.rmtree(creatives_dir, ignore_errors=True)
        return jsonify({"error": str(e)})
    except Exception as e:
        shutil.rmtree(creatives_dir, ignore_errors=True)
        return jsonify({"error": f"Analyse impossible : {e}"})

    token = uuid.uuid4().hex
    PLANS[token] = {
        "plan": plan,
        "platform": request.form.get("platform", "cm360"),
        "service_account": request.form.get("service_account", ""),
        "profile_id": request.form.get("profile_id", ""),
        "adform_client_id": request.form.get("adform_client_id", ""),
        "adform_client_secret": request.form.get("adform_client_secret", ""),
        "creatives_dir": creatives_dir,
        "rows": rows,   # conservé pour le rapport de diffusion (purgé avec le plan)
        "demo": request.form.get("demo") == "on",
        "created": time.time(),
    }
    html = _preview_html(rows, plan, errors, renames,
                         token if not errors else None)
    return jsonify({"html": html, "token": token, "errors": errors})


# ---------------------------------------------------------------------------
# Exécution du trafficking
# ---------------------------------------------------------------------------

@app.route("/run", methods=["POST"])
def run():
    token = (request.form.get("token")
             or (request.get_json(silent=True) or {}).get("token") or "")
    job = PLANS.pop(token, None)
    if not job:
        return jsonify({"error": "Plan expiré (plus d'une heure) — renvoyez le "
                                 "plan à l'analyse."})

    demo = job.get("demo", False)
    platform = job.get("platform", "cm360")
    if not demo:
        if platform == "cm360" and not job["service_account"]:
            return jsonify({"error": "CM360 : clé de compte de service manquante "
                                     "(ou activez le mode démo dans ⚙️)."})
        if platform == "adform" and not (job["adform_client_id"]
                                         and job["adform_client_secret"]):
            return jsonify({"error": "Adform : client ID et secret OAuth requis "
                                     "(ou activez le mode démo dans ⚙️)."})

    job_id = uuid.uuid4().hex
    label = next(iter(job["plan"].values())).name if job["plan"] else "Trafficking"
    JOBS[job_id] = {"log": [], "done": False, "report": None, "error": None,
                    "created": time.time(), "label": label,
                    # Paramètres du rapport de diffusion (même plateforme que le job)
                    "delivery": {k: job.get(k, "") for k in (
                        "rows", "platform", "service_account", "profile_id", "demo")}}

    store.save_job(job_id, JOBS[job_id])

    def worker():
        state = JOBS[job_id]
        def log(msg):
            state["log"].append(msg)
        try:
            if demo:
                log("[MODE DÉMO] Plateforme simulée — aucune écriture réelle.")
            adapter = build_adapter(
                platform="mock" if demo else platform,
                log=log,
                service_account=job["service_account"],
                profile_id=int(job["profile_id"]) if job["profile_id"].isdigit() else None,
                adform_client_id=job["adform_client_id"],
                adform_client_secret=job["adform_client_secret"],
                creatives_dir=job.get("creatives_dir", ""))
            state["report"] = traffic_plan(adapter, job["plan"], log=log)
        except Exception as e:
            state["error"] = f"{e}\n{traceback.format_exc()}"
        finally:
            # RGPD : purge des créatives extraites du ZIP dès la fin du job
            shutil.rmtree(job.get("creatives_dir") or "", ignore_errors=True)
            state["done"] = True
            store.save_job(job_id, state)

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/status/<job_id>")
def status(job_id):
    state = (JOBS.get(job_id) or store.load_job(job_id)
             or {"log": [], "done": True, "error": "job inconnu"})
    return jsonify({"log": state["log"], "done": state["done"], "error": state["error"]})


@app.route("/delivery/<job_id>", methods=["POST"])
def delivery(job_id):
    """Rapport de diffusion + réconciliation pour le plan d'un job (lecture seule)."""
    state = JOBS.get(job_id) or store.load_job(job_id)
    if not state or not state.get("delivery", {}).get("rows"):
        return jsonify({"error": "Plan introuvable (job inconnu ou purge après 1 h)."})
    d = state["delivery"]
    demo = d.get("demo", False)
    platform = "mock" if demo else d.get("platform", "cm360")
    if platform == "adform":
        return jsonify({"error": "Reporting Adform : pas encore disponible "
                                 "(utilisez CM360 ou le mode démo)."})
    if platform == "cm360" and not d.get("service_account"):
        return jsonify({"error": "CM360 : clé de compte de service manquante."})
    try:
        adapter = build_reporting_adapter(
            platform=platform, log=lambda m: None,
            service_account=d.get("service_account", ""),
            profile_id=int(d["profile_id"]) if str(d.get("profile_id", "")).isdigit() else None)
        deliveries, flags = report_for_plan(d["rows"], adapter)
    except SystemExit as e:
        return jsonify({"error": str(e)})
    except Exception as e:
        return jsonify({"error": f"Rapport impossible : {e}"})
    data = delivery_to_dict(adapter.name, deliveries, flags)
    return jsonify({"html": _delivery_html(data), "data": data})


def _delivery_html(data: dict) -> str:
    e = _html.escape
    out = [f"<p><b>Rapport de diffusion</b> [{e(data['platform'])}]</p>"]
    for line in data["reconciliation"]:
        out.append(f"<p>{e(line)}</p>")
    for c in data["campaigns"]:
        if not c["placements"]:
            continue
        out.append(f"<p><b>{e(c['name'])}</b> — par emplacement :</p><ul>")
        for p in c["placements"]:
            ctr = p["clicks"] / p["impressions"] * 100 if p["impressions"] else 0
            n = lambda v, f=",": format(v, f).replace(",", " ")
            out.append(f"<li>{e(p['name'])} : {n(p['impressions'])} imp., "
                       f"{n(p['clicks'])} clics (CTR {ctr:.2f} %), "
                       f"{n(p['spend'], ',.2f')} €</li>")
        out.append("</ul>")
    return "".join(out)


@app.route("/jobs")
def jobs_list():
    items = []
    for jid, st in sorted(JOBS.items(), key=lambda kv: -kv[1]["created"])[:20]:
        items.append({"id": jid, "label": st.get("label", "Trafficking"),
                      "done": st["done"], "error": bool(st["error"])})
    seen = {i["id"] for i in items}
    items += [j for j in store.list_jobs() if j["id"] not in seen]   # jobs d'avant redémarrage
    return jsonify({"jobs": items[:20]})


@app.route("/report/<job_id>")
def report(job_id):
    state = JOBS.get(job_id) or store.load_job(job_id)
    if not state or not state.get("report"):
        return "<p>Rapport indisponible (job inconnu, échec, ou purge après 1 h).</p>"
    return app.response_class(
        json.dumps(state["report"], ensure_ascii=False, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=rapport_trafficking.json"})


# ---------------------------------------------------------------------------
# RGPD : purge automatique des jobs/plans expirés
# ---------------------------------------------------------------------------

def purge_expired():
    """RGPD : supprime les jobs et plans expirés, avec leurs fichiers
    temporaires (créatives extraites) et leurs rapports."""
    now = time.time()
    for token, p in list(PLANS.items()):
        if now - p.get("created", now) > RETENTION_SECONDS:
            shutil.rmtree(p.get("creatives_dir") or "", ignore_errors=True)
            PLANS.pop(token, None)
    for jid in [j for j, s in JOBS.items()
                if now - s.get("created", now) > RETENTION_SECONDS]:
        JOBS.pop(jid, None)
    store.purge(RETENTION_SECONDS)


def _retention_loop():
    while True:
        time.sleep(600)
        purge_expired()


if __name__ == "__main__":
    threading.Thread(target=_retention_loop, daemon=True).start()
    app.run(host="127.0.0.1", port=5000, debug=False)

