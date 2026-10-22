# Trafficker

Couche adops côté agence, au-dessus de deux ad servers : CM360 et Adform (périmètre volontairement limité à ces deux plateformes) : ingestion de plans médias, nomenclatures, validation avant envoi, trafficking multi-plateformes, reporting réconcilié (livraison + pacing impressions et dépense), UI conversationnelle et serveur MCP. RGPD intégré (voir `conformite_rgpd.md`).

## Démarrage rapide

```bash
python -m venv venv && . venv/bin/activate
pip install -r requirements.txt -c requirements.lock   # versions figées
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
| `web/` (`index.html`, `web_api.py`, `build.py`, `worker.js`, `wheels/`), `wrangler.jsonc`, `package.json` | Version 100 % navigateur (Pyodide) servie gratuitement par Cloudflare |
| `wrangler.containers.jsonc`, `cloudflare/worker.js`, `.github/workflows/deploy-cloudflare.yml` | Mise en ligne sur Cloudflare Containers (déploiement en un clic depuis GitHub) |
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

## Agent de lecture des plans médias (`plan_agent.py`)

Le plan est lu « tel qu'il arrive » ; l'agent retrouve chaque information même hors de sa colonne :

- **Cases surlignées en jaune** : si le classeur (XLSX/XLS) contient des cases jaunes (jaune vif, jaune clair, or — couleurs directes ou de thème), l'agent ne lit **que** ces cases ; seuls les libellés (ligne d'en-tête du tableau, étiquettes « Annonceur », « Période »… à côté d'une case jaune) sont gardés pour comprendre les colonnes. Une case fusionnée jaune couvre toute sa plage. Sans case jaune, tout le fichier est lu. Un CSV n'a pas de couleurs : lecture complète.
- **Fichier** : CSV (`;` `,` tabulation `|`, UTF-8 ou Windows-1252), XLSX, XLS, toutes les feuilles ; la feuille et la ligne d'en-tête sont repérées automatiquement (titres, logos, lignes vides au-dessus).
- **Bloc d'informations** au-dessus du tableau : Client/Annonceur, Nom de campagne, Date de début, Date de fin (ou Période), **Objectif général**, Cible, Ciblage, Budget, URL → valeurs de campagne, appliquées à toutes les lignes (l'objectif général alimente la nomenclature). Dispositions reconnues : « Client : X » dans une cellule, libellé puis valeur à droite, ou bandeau de libellés avec les valeurs en dessous. Un bandeau de ce type n'est jamais pris pour l'en-tête du tableau.
- **Colonnes** : par l'en-tête (synonymes FR/EN, rapprochement approché), puis **par le contenu** quand l'en-tête ne dit rien : URL → destination, `300x250` → format, deux colonnes de dates → début/fin, `12 500 €` → budget, `<script>` → tag, `.mp4`/`.png` → créatives, `CPM` → mode d'achat, colonne de libellés la plus variée → emplacement.
- **Lignes** : cellules fusionnées complétées, lignes de total/titre ignorées, période « 02/11 – 15/12/2026 » découpée, plusieurs formats dans une cellule → une ligne par format, format/URL/mode d'achat retrouvés dans le nom ou une autre cellule, noms d'annonce/créative générés, dates propres à chaque ligne → la campagne couvre toute la période, budgets et volumes additionnés par campagne.
- **Formats et catégories d'emplacement** : dimensions lues telles quelles ou retrouvées dans le nom ; noms de formats IAB convertis (Pavé/MPU → 300x250, Méga-bannière → 728x90, Grand angle → 300x600, Billboard → 970x250, Bannière mobile → 320x50…) → emplacement **display** avec sa dimension ; preroll/in-stream/vidéo → **vidéo in-stream** ; aucun format reconnaissable → **tracking 1x1**. Colonne optionnelle `placement_category` (display/video/tracking) pour forcer ; reprise dans la colonne Compatibility de l'export CM360.
- **Nomenclature de base** (appliquée si aucun fichier de nomenclature n'est fourni) : emplacement `OBJECTIF-AUDIENCE-RÉGIE-CIBLAGE-FORMAT`, créative `RÉGIE-FORMAT-MESSAGE`, annonce = nom de l'emplacement ; majuscules sans accents, espaces → `_`, segments absents sautés, homonymes suffixés `-2` (jamais fusionnés). L'agent lit objectif (texte ; un « objectif » chiffré reste un volume), audience/cible, régie/support, ciblage, format tel qu'écrit (« Pavé ») et message/accroche. Sans objectif, audience ni ciblage dans le plan, les noms d'origine sont gardés. Un fichier de nomenclature client remplace la base.
- **Rapport de provenance** (CLI, UI, MCP, version navigateur) : d'où vient chaque champ, ce qui a été déduit, ignoré ou reste introuvable. Rien n'est inventé : une campagne introuvable bloque l'envoi.

**Option IA** (désactivée par défaut) : `TRAFFICKER_LLM=1`, `TRAFFICKER_LLM_MODEL=<modèle Claude>`, `ANTHROPIC_API_KEY`, `pip install anthropic`. Seules les colonnes encore inconnues et 3 valeurs d'exemple sont envoyées ; la réponse est filtrée (noms canoniques uniquement, pas de doublon).

## Specs créatives CM360

Base de référence : `specs/cm360_specs_creatives.xlsx` (12 specs officielles, sources aide CM360), convertie en `specs/cm360_creative_specs.json` et appliquée par `creative_specs.py` à chaque fichier créatif fourni (CLI `--creatives-dir`, ZIP de l'UI, fichiers joints dans la version navigateur) :

| Type | Fichiers acceptés | Contrôles |
|---|---|---|
| Display image | GIF, JPG, PNG, WBMP | 9,5 Mo max ; ≤ 4000×4000 ; ratio = emplacement ; recommandé jusqu'à 2× la taille |
| Display HTML5 | ZIP, ADZ | 10 Mo max ; 100 fichiers max ; types autorisés ; click tag obligatoire ; pas de `%`, de .zip imbriqué, de stockage local ; https ; `meta ad.size` ; image de secours |
| Vidéo in-stream | MP4, MOV, M4V, AVI, MPEG, MPG, WEBM, WMV | 1 Go max ; 15 ou 30 s ; 1280×720 / 1920×1080 / 1440×1080 (portrait, carré) ; 16:9, 4:3, 9:16, 3:4 ; H.264 |
| Audio in-stream | MP3, OGG, OGA | 1 Go max |

« Erreur » = refusé par CM360 : l'envoi et les exports sont bloqués. « Alerte » = accepté mais hors recommandation. Un fichier non joint est signalé sans bloquer. La version navigateur affiche aussi le rappel des specs de chaque type présent. Création HTML5/audio par l'API CM360 non encore validée : passer par l'export Campaign spreadsheet.

## Informations introuvables : laissées vides, « à compléter »

Ce que l'agent ne trouve pas (date de début, date de fin, URL de destination) n'est plus une erreur à la préparation : la case reste **vide** et l'aperçu liste « ✏️ À compléter » avec les objets concernés (campagne, annonces). Les exports CM360 et Adform sont produits avec ces cases vides, à remplir avant l'import ; la simulation l'indique. Une valeur illisible (date impossible, fin avant début) est traitée de même : vidée et listée avec la valeur d'origine. **L'envoi réel vers CM360/Adform reste bloqué** tant qu'une information manque. Le rapport de diffusion demande les dates.

## Validation avant envoi

Le dry-run (et l'UI) signalent : champs manquants, tailles invalides, dates inexistantes ou fin avant début, dates incohérentes entre lignes d'une même campagne, doublons de créatives, créatives sans snippet/chemin.

## UI : authentification et persistance

- Login désactivé par défaut (local uniquement). Pour l'activer : `TRAFFICKER_PASSWORD` (secret chiffré par l'hébergeur, ex. Cloudflare) ou, mieux, un hash :
  ```bash
  export TRAFFICKER_PASSWORD_HASH="$(python -c 'from werkzeug.security import generate_password_hash as g; print(g("mon-mot-de-passe"))')"
  export TRAFFICKER_USER=admin            # défaut
  export TRAFFICKER_SECRET_KEY="une-longue-valeur-aleatoire"   # sinon aléatoire à chaque démarrage
  ```
  5 échecs en 5 minutes bloquent l'IP (429). Derrière HTTPS en production, ajoutez `SESSION_COOKIE_SECURE`.
- État dans SQLite (`TRAFFICKER_DB`, défaut `trafficker.db`, mode WAL) : plans analysés, jobs (journal mis à jour en direct), échecs de login. Visible après redémarrage et depuis tous les processus, purgé après 1 h. **Aucun secret stocké** : clé de compte de service et secret Adform sont renvoyés par le navigateur à chaque lancement ou rapport.

## Version 100 % navigateur (Cloudflare, gratuit)

`web/` : la même logique Python tourne **dans le navigateur** grâce à Pyodide (WebAssembly), servie comme site statique par Cloudflare (offre gratuite). Adresse : `https://trafficker.<ton-sous-domaine>.workers.dev`.

- Fonctions : analyse et validation du plan (CSV, XLSX, XLS, export CM360, colonnes libres), typage des créatives (display, vidéo in-stream, tracking auto), nomenclatures, exports **Campaign spreadsheet CM360** et **classeur bulk Adform**, trafficking et rapport de diffusion **simulés**.
- **Structure** : 1 plan média = 1 annonceur = 1 campagne → 1 ou plusieurs objectifs → 1 ou plusieurs régies → 1 ou plusieurs emplacements (granularité format / ciblage / devices) → 1 ou plusieurs créatives. Campagne et annonceur sont uniques (valeurs divergentes fusionnées et signalées) et se saisissent une fois en tête du volet ; un package CM360 est créé par régie et objectif (`PACKAGE-RÉGIE-OBJECTIF`) quand le plan n'en donne pas ; colonne Devices lue.
- **Écran de contrôle en deux volets** : à gauche, le plan média classé par l'agent dans un **tableau modifiable** (cases orange = à compléter, ajout/suppression de lignes, dates JJ/MM/AAAA, formats « Pavé » convertis) ; à droite, l'**aperçu tel qu'il apparaîtra dans CM360** (Campagne > Site > Package > Emplacement > Annonce > Créative ; colonnes Name, ID « nouveau », Start/End date, Type, Asset type, Compatibility, Dimensions ; lignes repliables). Chaque modification recalcule la nomenclature, les contrôles et l'aperçu ; les exports et la simulation partent du tableau modifié. Colonne optionnelle `package` (groupe d'emplacements).
- **Choix de l'ad server** au départ (CM360 ou Adform) : l'aperçu et l'export s'adaptent. Aperçu **Adform** fidèle à la plateforme, avec le menu de la campagne en liste déroulante : **Campagne** (campagne puis « Direct Line Item » : Media = régie, Type Direct, Status, ID, Start/End Date, Non-Programmatic Budget, Volume en Imps), **Bannières** (type, taille, line item, URL de clic) et **Tags** (taille, type de tag, nombre de bannières). Les informations manquantes ne sont plus listées : elles apparaissent en orange dans le plan et dans l'aperçu ; le détail de lecture et de nomenclature est replié.
- Confidentialité : aucun fichier ne quitte le navigateur (test automatique : aucune requête hors du site). Pas de compte, pas de base, rien à purger.
- Limite : pas d'appel direct aux API CM360/Adform depuis le navigateur — le trafficking réel passe par la version serveur (UI Flask, CLI ou MCP).
- Déploiement : dépôt connecté au Worker `trafficker` (Workers Builds), réglages par défaut. `npx wrangler deploy` lance `python3 web/build.py` (copie du moteur, du modèle Adform, des wheels openpyxl/xlrd et du cœur Pyodide — auto-hébergé, sans CDN) puis publie `web/dist`.
- Accès restreint (facultatif, gratuit) : Cloudflare Zero Trust → Access → application sur l'adresse du Worker, connexion par code envoyé par e-mail.
- Local : `npm ci && python3 web/build.py && python3 -m http.server -d web/dist 8000`.

### Version serveur sur Cloudflare Containers (offre payante)

`wrangler.containers.jsonc` + `cloudflare/worker.js` + workflow GitHub `deploy-cloudflare` (secrets `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `TRAFFICKER_PASSWORD`). Nécessite Workers Paid et un jeton avec la permission Containers.

## Déploiement (SaaS)

```bash
export DOMAIN=trafficker.mon-agence.fr
export TRAFFICKER_PASSWORD_HASH='...'   # voir « UI : authentification »
export TRAFFICKER_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
docker compose up -d --build
```

gunicorn (`TRAFFICKER_WORKERS` processus, 2 par défaut, 8 threads chacun : plans analysés, jobs et compteur anti-force brute sont en SQLite, donc partagés entre processus ; une seule machine — plusieurs machines demanderaient PostgreSQL), utilisateur non root, base SQLite dans un volume, cookie de session `Secure`, HTTPS et HSTS par Caddy, sonde `/healthz`. À la charge de l'agence : hébergeur dans l'UE et DPA signés (voir `conformite_rgpd.md`). Image Docker construite et testée (login, analyse, lancement, rapport, utilisateur non root) ; configuration Cloudflare validée par `wrangler deploy --dry-run`.

## Sécurité et rétention

- Login actif : **toutes** les routes exigent la session (garde global `before_request`), sauf `/login` et `/healthz` ; un test parcourt la table des routes pour qu'aucune nouvelle route n'y échappe.
- ZIP de créatives : extraction contrôlée (`safe_extract`) — refus des chemins absolus, `..`, lettres de lecteur, liens symboliques ; 200 fichiers et 200 Mo décompressés au plus (comptés pendant l'extraction).
- Rétention 1 h : worker démarré dès le chargement de l'UI (quel que soit le serveur), purge aussi déclenchée par les requêtes (au plus une fois par minute), et un job expiré n'est jamais relu, même avant la purge.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q tests        # le test navigateur est ignoré si Chromium est absent
```

## État et reste à faire

Validés en local (mock) : trafficking, reporting, UI, MCP. **Non validés faute d'accès réel** : CM360 (clé de compte de service) et les statuts/colonnes de l'API Reports (`mediaCost` → colonne « Media Cost »). Types CM360 `TRACKING_TEXT`, `INSTREAM_VIDEO` et `AD_SERVING_TRACKING` : corps de requête testés avec un service factice, **à valider sur un vrai compte**. Adform : authentification et diagnostic seulement, création d'objets à écrire avec un accès réel. Pas implémentés : HTML5, Floodlight, agent d'ingestion IA, multi-agences, déploiement SaaS.
