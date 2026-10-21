# Trafficker

Couche adops côté agence, au-dessus de deux ad servers : CM360 et Adform (périmètre volontairement limité à ces deux plateformes) : ingestion de plans médias, nomenclatures, validation avant envoi, trafficking multi-plateformes, reporting réconcilié (livraison + pacing impressions et dépense), UI conversationnelle et serveur MCP. RGPD intégré (voir `conformite_rgpd.md`).

## Démarrage rapide

```bash
python -m venv venv && . venv/bin/activate
pip install -r requirements.txt
python cm360_trafficker.py plan_media_template.csv --dry-run          # 1. validation
python cm360_trafficker.py plan_media_template.csv --platform mock     # 2. démo
python cm360_trafficker_ui.py                                          # 3. UI -> http://127.0.0.1:5000
python cm360_reporting.py plan_media_template.csv --platform mock      # 4. reporting démo
python cm360_mcp_server.py                                             # 5. serveur MCP (stdio)
```

## Fichiers

| Fichier | Rôle |
|---|---|
| `cm360_trafficker.py` | Moteur : lecture/validation du plan, nomenclatures, adaptateurs CM360 / Adform / mock |
| `cm360_reporting.py` | Reporting : diffusion, pacing impressions et dépense |
| `cm360_trafficker_ui.py` | UI conversationnelle (Flask) : analyse, trafficking, rapport de diffusion, login optionnel |
| `trafficker_store.py` | Persistance SQLite des jobs (rétention 1 h) |
| `cm360_mcp_server.py` | Serveur MCP : `analyze_plan`, `traffic`, `check_access`, `report_delivery` |
| `nomenclatures.json`, `plan_media_template.csv` | Templates |
| `guide_mise_en_place.md`, `conformite_rgpd.md` | Guide complet, RGPD |
| `tests/` | pytest : moteur, reporting, UI (client Flask) et parcours navigateur (Playwright) |

## Colonnes optionnelles du plan (reporting)

- `objective_impressions` : objectif d'impressions de la campagne → pacing impressions.
- `budget_eur` : budget média de la campagne (€) → pacing dépense. Nombres tolérés : `4000`, `4 000,50`.

Pacing = livré / (objectif × fraction du vol écoulée) : OK entre 80 % et 120 %, EN RETARD en dessous, EN AVANCE au-dessus ; « NON DÉMARRÉE » avant le début du vol.

## Typage automatique des créatives

| Dans le plan | Type | Catégorie |
|---|---|---|
| tag tiers (`snippet`) | `REDIRECT` | display |
| fichier image (`creative_path` png/jpg/gif) | `IMAGE` | display |
| fichier vidéo (`creative_path` mp4/mov/webm…) | `VIDEO` | in-stream video |
| **rien de partagé** (ni tag, ni fichier) | `TRACKING` | créative de tracking **générée automatiquement** |

`creative_type` (REDIRECT/IMAGE/VIDEO/TRACKING) ou `creative_category` (display/video/tracking) forcent le type si besoin. Un format de fichier inconnu (zip, html…) est refusé à la validation. Une annonce ne peut pas mélanger tracking et display/vidéo (CM360 : annonce `AD_SERVING_TRACKING` dédiée).

## Validation avant envoi

Le dry-run (et l'UI) signalent : champs manquants, tailles invalides, dates inexistantes ou fin avant début, dates incohérentes entre lignes d'une même campagne, doublons de créatives, créatives sans snippet/chemin.

## UI : authentification et persistance

- Login désactivé par défaut (local uniquement). Pour l'activer :
  ```bash
  export TRAFFICKER_PASSWORD_HASH="$(python -c 'from werkzeug.security import generate_password_hash as g; print(g("mon-mot-de-passe"))')"
  export TRAFFICKER_USER=admin            # défaut
  export TRAFFICKER_SECRET_KEY="une-longue-valeur-aleatoire"   # sinon aléatoire à chaque démarrage
  ```
  5 échecs en 5 minutes bloquent l'IP (429). Derrière HTTPS en production, ajoutez `SESSION_COOKIE_SECURE`.
- Jobs enregistrés dans SQLite (`TRAFFICKER_DB`, défaut `trafficker.db`) : visibles après redémarrage, purgés après 1 h. Aucun secret n'est stocké.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q tests        # le test navigateur est ignoré si Chromium est absent
```

## État et reste à faire

Validés en local (mock) : trafficking, reporting, UI, MCP. **Non validés faute d'accès réel** : CM360 (clé de compte de service) et les statuts/colonnes de l'API Reports (`mediaCost` → colonne « Media Cost »). Types CM360 `TRACKING_TEXT`, `INSTREAM_VIDEO` et `AD_SERVING_TRACKING` : corps de requête testés avec un service factice, **à valider sur un vrai compte**. Adform : authentification et diagnostic seulement, création d'objets à écrire avec un accès réel. Pas implémentés : HTML5, Floodlight, agent d'ingestion IA, multi-agences, déploiement SaaS.
