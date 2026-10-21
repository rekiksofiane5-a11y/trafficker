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
| `cm360_bulk.py` | Format « Campaign spreadsheet » CM360 (Bulk Editor) : export du plan et import comme source |
| `adform_bulk.py`, `templates/` | Export campagnes + commandes au format bulk Adform (classeur v6, données d'exemple retirées) |
| `ingest.py` | Ingestion d'un plan à colonnes libres (synonymes FR/EN, normalisation, option IA) |
| `Dockerfile`, `docker-compose.yml`, `Caddyfile` | Déploiement (gunicorn + HTTPS automatique) |
| `cm360_mcp_server.py` | Serveur MCP : `analyze_plan`, `traffic`, `check_access`, `report_delivery`, `export_campaign_spreadsheet`, `export_adform_bulk` |
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

## Campaign spreadsheet CM360 (Bulk Editor)

- **Export** (sans clé API) : `python cm360_trafficker.py plan.csv --export-bulk campaign_spreadsheet.xlsx` — un fichier à importer dans le Bulk Editor de CM360. Aussi dans l'UI (bouton « ⬇ Campaign spreadsheet CM360 » après l'analyse) et via l'outil MCP `export_campaign_spreadsheet`. Une ligne par placement + annonce + créative ; les 72 colonnes sont celles de l'export réel.
- **Import** : `python cm360_trafficker.py export.xls --dry-run --campaign-name NOM --advertiser-name ANNONCEUR` (.xls ou .xlsx ; détecté à ses en-têtes). Le format ne contient ni campagne ni annonceur : à fournir (CLI, MCP, ou ⚙️ dans l'UI). Dates de campagne = plus petit début / plus grande fin des placements ; `objective_impressions` = unités des placements CPM ; `budget_eur` = coûts, comptés une fois par placement. Dates lues en ISO ou JJ/MM/AAAA.
- **Limites** : l'export fourni ne contenait que les en-têtes ; le vocabulaire des valeurs (Type d'annonce/créative, compatibilité, structure de coût) est déduit de l'interface CM360 et regroupé dans `VOCAB` (`cm360_bulk.py`) pour être corrigé avec un export rempli. Les créatives non-tracking n'ont ni tag ni fichier dans ce format : à compléter (`snippet` / `creative_path`) avant trafficking.

## Classeur bulk Adform

`python cm360_trafficker.py plan.csv --export-adform-bulk adform_bulk.xlsx [--adform-campaign-type Non-programmatic]` (aussi dans l'UI : « ⬇ Classeur bulk Adform », et via l'outil MCP `export_adform_bulk`).

- Basé sur le classeur Adform v6 (feuilles Campaigns, Orders, Programmatic line items, Banners…) ; la structure n'est pas modifiée, comme l'exige Adform. Un garde-fou vérifie les en-têtes : un classeur d'une autre version est refusé.
- **Généré** : 1 ligne Campaigns et 1 ligne Orders par campagne (nom, dates, budget `budget_eur` → « Non-Programmatic budget », réglages par défaut repris de l'exemple : EUR, fuseau Paris, attribution 30 jours… voir `ADFORM_DEFAULTS`).
- **Non généré** : placements, annonces, créatives. « Programmatic line items » exige des sources d'inventaire ou des deals (programmatique) et « Banners » assigne des bannières existantes par ID. Ils restent à créer dans Adform ou via l'API (adaptateur à compléter avec un accès réel).
- Noms de campagne : 256 caractères max, sans `< > * ' " ? | ; \` (règle Adform, contrôlée).
- Listes de valeurs Adform (types de campagne, modes de saisie…) : lues dans les listes déroulantes du classeur fourni.
- Le classeur ne peut pas être importé comme plan (il ne décrit ni placements ni créatives).

## Ingestion d'un plan quelconque

Un plan dont les colonnes ne sont pas canoniques (« Campagne », « Support », « Format (px) », « Début », « Budget HT », « URL de destination »…) est converti automatiquement : synonymes FR/EN puis rapprochement approché, normalisation des valeurs (dates JJ/MM/AAAA, `300 x 250 px`, `4 000,50 €`, « Coût pour mille » → CPM). Le rapport (colonnes reconnues, ignorées, champs obligatoires manquants) s'affiche en CLI, dans l'UI et dans le MCP. `--campaign-name` / `--advertiser-name` comblent une colonne absente.

**Option IA** (désactivée par défaut) : `TRAFFICKER_LLM=1`, `TRAFFICKER_LLM_MODEL=<modèle Claude>`, `ANTHROPIC_API_KEY`, `pip install anthropic`. Seules les colonnes encore inconnues et 3 valeurs d'exemple sont envoyées ; la réponse est filtrée (noms canoniques uniquement, pas de doublon).

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

## Déploiement (SaaS)

```bash
export DOMAIN=trafficker.mon-agence.fr
export TRAFFICKER_PASSWORD_HASH='...'   # voir « UI : authentification »
export TRAFFICKER_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
docker compose up -d --build
```

gunicorn (1 processus, 8 threads), utilisateur non root, base SQLite dans un volume, cookie de session `Secure`, HTTPS et HSTS par Caddy, sonde `/healthz`. À la charge de l'agence : hébergeur dans l'UE et DPA signés (voir `conformite_rgpd.md`). Le Dockerfile n'a pas été construit dans l'environnement de développement (pas de Docker) ; gunicorn a été testé.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q tests        # le test navigateur est ignoré si Chromium est absent
```

## État et reste à faire

Validés en local (mock) : trafficking, reporting, UI, MCP. **Non validés faute d'accès réel** : CM360 (clé de compte de service) et les statuts/colonnes de l'API Reports (`mediaCost` → colonne « Media Cost »). Types CM360 `TRACKING_TEXT`, `INSTREAM_VIDEO` et `AD_SERVING_TRACKING` : corps de requête testés avec un service factice, **à valider sur un vrai compte**. Adform : authentification et diagnostic seulement, création d'objets à écrire avec un accès réel. Pas implémentés : HTML5, Floodlight, agent d'ingestion IA, multi-agences, déploiement SaaS.
