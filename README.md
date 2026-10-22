# Umnia

Umnia est l'agent de trafficking et de reporting de l'agence (anciennement « Trafficker ») : il lit n'importe quel plan média, le classe, applique la nomenclature et prépare la mise en ligne CM360 / Adform. Les identifiants techniques (Worker `trafficker`, secret `TRAFFICKER_PASSWORD`, modules `cm360_trafficker*.py`) gardent leur nom.

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

**Création de la campagne** (aide CM360 « Configurer une campagne ») : champs lus dans le plan (code de facturation, ID externe, publicité politique UE) ou saisis dans « Création de la campagne dans CM360 » ; fiche de création à recopier dans CM360 avant l'import ; contrôles (nom < 512 car., fin ≥ début, début pas dans le passé, page par défaut, code de facturation ≤ 64 car., ID externe ≤ 50 car. A-Z 0-9 - _, déclaration UE). Règles réunies dans `docs/connaissances_cm360.md`.

**Constaté sur un vrai compte CM360** : une ligne sans Site ID ni nom de site existant ne crée ni emplacement, ni annonce, ni assignation — seules les créatives sont importées. Umnia l'affiche avant l'export (« Avant l'import dans CM360 ») et demande confirmation ; colonne « ID site CM360 » dans le plan (plus sûr que le nom). Packages : pas encore écrits dans le Campaign spreadsheet (format à confirmer sur un export CM360 rempli contenant un package).

## Classeur bulk Adform

`python cm360_trafficker.py plan.csv --export-adform-bulk adform_bulk.xlsx [--adform-campaign-type Non-programmatic]` (aussi dans l'UI : « ⬇ Classeur bulk Adform », et via l'outil MCP `export_adform_bulk`).

- Basé sur le classeur Adform v6 (feuilles Campaigns, Orders, Programmatic line items, Banners…) ; la structure n'est pas modifiée, comme l'exige Adform. Un garde-fou vérifie les en-têtes : un classeur d'une autre version est refusé.
- **Généré** : 1 ligne Campaigns et 1 ligne Orders par campagne (nom, dates, budget `budget_eur` → « Non-Programmatic budget », réglages par défaut repris de l'exemple : EUR, fuseau Paris, attribution 30 jours… voir `ADFORM_DEFAULTS`).
- **Non généré** : placements, annonces, créatives. « Programmatic line items » exige des sources d'inventaire ou des deals (programmatique) et « Banners » assigne des bannières existantes par ID. Ils restent à créer dans Adform ou via l'API (adaptateur à compléter avec un accès réel).
- Noms de campagne : 256 caractères max, sans `< > * ' " ? | ; \` (règle Adform, contrôlée).
- Listes de valeurs Adform (types de campagne, modes de saisie…) : lues dans les listes déroulantes du classeur fourni.
- Le classeur ne peut pas être importé comme plan (il ne décrit ni placements ni créatives).

## Agent de lecture des plans médias (`plan_agent.py`)

Le plan est lu « tel qu'il arrive » ; Umnia retrouve chaque information même hors de sa colonne :

- **Cases surlignées en jaune** : si le classeur (XLSX/XLS) contient des cases jaunes (jaune vif, jaune clair, or — couleurs directes ou de thème), l'agent ne lit **que** ces cases ; seuls les libellés (ligne d'en-tête du tableau, étiquettes « Annonceur », « Période »… à côté d'une case jaune) sont gardés pour comprendre les colonnes. Une case fusionnée jaune couvre toute sa plage. Sans case jaune, tout le fichier est lu. Un CSV n'a pas de couleurs : lecture complète.
- **Fichier** : CSV (`;` `,` tabulation `|`, UTF-8 ou Windows-1252), XLSX, XLS, toutes les feuilles ; la feuille et la ligne d'en-tête sont repérées automatiquement (titres, logos, lignes vides au-dessus).
- **Bloc d'informations** au-dessus du tableau : Client/Annonceur, Nom de campagne, Date de début, Date de fin (ou Période), **Objectif général**, Cible, Ciblage, Budget, URL → valeurs de campagne, appliquées à toutes les lignes (l'objectif général alimente la nomenclature). Dispositions reconnues : « Client : X » dans une cellule, libellé puis valeur à droite, ou bandeau de libellés avec les valeurs en dessous. Un bandeau de ce type n'est jamais pris pour l'en-tête du tableau.
- **Colonnes** : par l'en-tête (synonymes FR/EN, rapprochement approché), puis **par le contenu** quand l'en-tête ne dit rien : URL → destination, `300x250` → format, deux colonnes de dates → début/fin, `12 500 €` → budget, `<script>` → tag, `.mp4`/`.png` → créatives, `CPM` → mode d'achat, colonne de libellés la plus variée → emplacement.
- **Lignes** : cellules fusionnées complétées, lignes de total/titre ignorées, période « 02/11 – 15/12/2026 » découpée, plusieurs formats dans une cellule → une ligne par format, format/URL/mode d'achat retrouvés dans le nom ou une autre cellule, noms d'annonce/créative générés, dates propres à chaque ligne → la campagne couvre toute la période, budgets et volumes additionnés par campagne.
- **Formats et catégories d'emplacement** : dimensions lues telles quelles ou retrouvées dans le nom ; noms de formats IAB convertis (Pavé/MPU → 300x250, Méga-bannière → 728x90, Grand angle → 300x600, Billboard → 970x250, Bannière mobile → 320x50…) → emplacement **display** avec sa dimension ; preroll/in-stream/vidéo → **vidéo in-stream** ; aucun format reconnaissable → **tracking 1x1**. Colonne optionnelle `placement_category` (display/video/tracking) pour forcer ; reprise dans la colonne Compatibility de l'export CM360.
- **Plusieurs ciblages dans une cellule** (« Socio-démo : … Ciblage contextuel : … + ciblage sur les concurrents : … Ciblage comportemental : … ») : découpés en segments (Socio-démo, Contextuel, Concurrents, Comportemental, Retargeting, Géo, Lookalike, Data 1st party, Affinité), **un emplacement par ciblage et par format**, et **un package par ciblage** ; le détail (mots-clés, tranches d'âge…) va dans la colonne « Détail du ciblage ».
- **Dates en toutes lettres** : « 16 au 23 avril 2025 », « du 28 mars au 4 avril 2025 », « 1er - 15 mai 2026 ».
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

Ce qu'Umnia ne trouve pas (date de début, date de fin, URL de destination) n'est plus une erreur à la préparation : la case reste **vide** et l'aperçu liste « ✏️ À compléter » avec les objets concernés (campagne, annonces). Les exports CM360 et Adform sont produits avec ces cases vides, à remplir avant l'import ; la simulation l'indique. Une valeur illisible (date impossible, fin avant début) est traitée de même : vidée et listée avec la valeur d'origine. **L'envoi réel vers CM360/Adform reste bloqué** tant qu'une information manque. Le rapport de diffusion demande les dates.

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
- **Structure** : 1 plan média = 1 annonceur = 1 campagne → 1 ou plusieurs objectifs → 1 ou plusieurs régies → 1 ou plusieurs emplacements (granularité format / ciblage / devices) → 1 ou plusieurs créatives. Campagne et annonceur sont uniques (valeurs divergentes fusionnées et signalées) et se saisissent une fois en tête du volet ; un package CM360 est créé par régie, objectif et ciblage (`PACKAGE-RÉGIE-OBJECTIF-CIBLAGE`) quand le plan n'en donne pas ; colonne Devices lue.
- **Écran de contrôle en deux volets** : à gauche, le plan média classé par Umnia dans un **tableau modifiable** (cases orange = à compléter, ajout/suppression de lignes, dates JJ/MM/AAAA, formats « Pavé » convertis) ; à droite, l'**aperçu tel qu'il apparaîtra dans CM360** (Campagne > Site > Package > Emplacement > Annonce > Créative ; colonnes Name, ID « nouveau », Start/End date, Type, Asset type, Compatibility, Dimensions ; lignes repliables). Chaque modification recalcule la nomenclature, les contrôles et l'aperçu ; les exports et la simulation partent du tableau modifié. Colonne optionnelle `package` (groupe d'emplacements).
- **Validation par étapes** : (1) **emplacements** sous leur site (régie), regroupables en package (cocher puis « Créer un package ») ; « Valider les emplacements » → (2) **annonces et créatives** ajoutées : 1 annonce = 1 emplacement × 1 créative, nommée par défaut « emplacement-créative ». Les exports et la simulation s'activent après la validation. **Édition directe dans l'aperçu** : double-clic pour renommer (site, package, emplacement, annonce, créative, campagne), glisser un emplacement sur un site ou un package, une annonce/créative sur un autre emplacement ; un clic surligne les lignes du plan concernées. Les noms imposés sont reportés dans le plan (colonnes « Nom … (imposé) ») et priment sur la nomenclature.
- **Modification en masse (bulk edit)** : cases à cocher sur chaque ligne du plan (Maj + clic = plage, case d'en-tête = tout) ; barre d'actions : choisir un champ et une valeur (valeurs existantes proposées, vide = effacer) puis **Appliquer**, **Dupliquer** ou **Supprimer** les lignes sélectionnées ; l'aperçu se recalcule.
- **Confort** : colonnes redimensionnables (glisser le bord de l'en-tête, double-clic = large, flèches au clavier ; largeurs mémorisées), contenu complet en infobulle ; après la production, la zone de dépôt se replie en une ligne (« Modifier le plan ou relancer »).
- **Choix de l'ad server** au départ (CM360 ou Adform) : l'aperçu et l'export s'adaptent. Aperçu **Adform** fidèle à la plateforme, avec le menu de la campagne en liste déroulante : **Campagne** (campagne puis « Direct Line Item » : Media = régie, Type Direct, Status, ID, Start/End Date, Non-Programmatic Budget, Volume en Imps), **Bannières** (type, taille, line item, URL de clic) et **Tags** (taille, type de tag, nombre de bannières). Les informations manquantes ne sont plus listées : elles apparaissent en orange dans le plan et dans l'aperçu ; le détail de lecture et de nomenclature est replié.
- **Interface** : page de connexion, puis barre du haut (logo, modes **Trafficking / Reporting**, recherche, menu Thème auto / clair / sombre, menu Compte : Paramètres, Administration pour les admins, Déconnexion ; bouton **Historique**) et panneau **Historique** à gauche (récents « Mes tâches » / « Agence », recherche, ＋ Nouvelle tâche ; chaque tâche avec icône, statut Brouillon / En cours / Terminée / Planifiée et « il y a … »), repliable et mémorisé.
- **Tâche** : la pop-up de création demande nom de la tâche, annonceur, ad server, nom de la campagne, ID agence (campagne et annonceur saisis ici priment sur ceux du fichier). Dans la tâche : dépôt du plan (cellules surlignées en jaune fluo = ce que lit l'agent), **instructions supplémentaires** (une par ligne, `Clé : valeur` — campagne, annonceur, début, fin, période, URL, régie, objectif, audience, ciblage, devices, package ; les autres sont notées sans être interprétées), puis **Lancer la production**. La tâche s'enregistre au fil de l'eau (plan classé, étape, instructions) et se rouvre telle quelle.
- **Comptes et tâches** : API du Worker (`/api/*`) et base **D1** `trafficker` (offre gratuite). Mots de passe PBKDF2-SHA256 salés, session en cookie HttpOnly/Secure/SameSite 12 h, blocage après 5 échecs en 5 min par IP, contrôle d'origine sur les écritures. Premier passage : création du compte administrateur avec la **clé d'installation** = valeur du secret `TRAFFICKER_PASSWORD` du Worker. Sans `/api` (serveur statique, tests), mode local : tâches dans le navigateur.
- Confidentialité : le plan média est lu dans le navigateur et n'est jamais envoyé en fichier ; seul le **plan classé** (tableau modifié) d'une tâche est enregistré en D1 pour la retrouver. Aucune requête hors du site (test automatique).
- Limite : pas d'appel direct aux API CM360/Adform depuis le navigateur — le trafficking réel passe par la version serveur (UI Flask, CLI ou MCP).
- Déploiement : dépôt connecté au Worker `trafficker` (Workers Builds), réglages par défaut. `npx wrangler deploy` lance `python3 web/build.py` (copie du moteur, du modèle Adform, des wheels openpyxl/xlrd et du cœur Pyodide — auto-hébergé, sans CDN) puis publie `web/dist`.
- Accès restreint (facultatif, gratuit) : Cloudflare Zero Trust → Access → application sur l'adresse du Worker, connexion par code envoyé par e-mail.
- Local : `npm ci && python3 web/build.py && python3 -m http.server -d web/dist 8000`.

### Reporting (mode Reporting de l'interface)

1. **Campagne** : recherche de l'annonceur puis de la campagne **dans l'ad server** (API via le Worker) ; Umnia lit les emplacements et en déduit les régies (sites CM360 / médias Adform).
2. **Template** :
   - **Check de mise en ligne** : toutes les régies et tous les emplacements, statut par emplacement (données reçues / aucune donnée / pas encore démarré) et par régie (complet / partiel / aucune donnée), petit tableau de bord (impressions, clics, CTR, emplacements et régies avec données, dernière donnée, impressions par régie), alerte sur les emplacements muets, Excel (Synthèse, Par régie, Emplacements, Données jour).
   - **Report d'envoi aux régies** : un bloc par régie (seules les régies de la campagne sont proposées, « ＋ Ajouter une régie »), e-mails libres avec **carnet d'adresses** par régie (mémorisé par agence en D1), calendrier (quotidien, hebdomadaire avec jours, mensuel ; cumul depuis le début ou période écoulée ; premier et dernier envoi ; message), **aperçu de l'Excel** envoyé à chaque régie et téléchargement. « Programmer les envois » : CM360 crée un rapport programmé par régie (filtres campagne + site, format Excel, destinataires) et l'envoie lui-même par e-mail. Adform : pas de rapport programmé par API — le calendrier est enregistré dans Umnia, le rapport est à programmer dans Adform (Excel prêt).
- **Rythme de diffusion** (check) : « Plan média lié » = une tâche de trafficking de l'agence (proposée automatiquement : même annonceur, campagne la plus proche). Les emplacements de l'ad server sont rapprochés des lignes du plan par leur nom final (nomenclature) ; par emplacement, par régie et pour la campagne : prévu total, **prévu à date** (linéaire sur les dates de diffusion de l'ad server, jusqu'à la veille), livré, **rythme** (< 90 % en retard, > 110 % en avance), **projection de fin**, **budget consommé estimé** (budget × livré / prévu). Sans objectif par ligne : objectif global de la campagne. Onglet « Rythme » dans l'Excel. Une ligne du plan éclatée en plusieurs emplacements (formats, ciblages) voit son budget et son volume répartis à parts égales.
- **Reports programmés** : pause / reprise, modification (destinataires, calendrier) et suppression depuis Umnia ; CM360 : le rapport programmé est mis à jour ou supprimé dans CM360 ; Adform : à répercuter dans Adform.
- **Diagnostic** (Administration → Connexions ad servers) : « Tester CM360 / Adform » demande un jeton puis lit les annonceurs, et affiche l'erreur exacte sinon.
- **Mode fichier (sans API)** : « Importer un export de rapport CM360 » (CSV / Excel du Report builder ou d'un rapport hors ligne ; exemple : `web/exemple_export_cm360.csv`) → campagne, emplacements, régies et diffusion jour par jour lus dans le fichier ; dates de campagne modifiables ; check, rythme (plan lié : les emplacements absents de l'export sont signalés « aucune donnée »), Excel et reports régie comme avec l'API (envoi à programmer dans CM360).
- **Prompt de rapport CM360** (3e template, sans accès API) : demande en français (« clics par régie la semaine dernière », exemples en un clic) → questions sur ce qui manque (campagne, période, découpage) → prompt anglais à coller dans CM360 → Report builder → Instant reporting → « Generate report », réglages équivalents (Flat table, Date range, dimensions, métriques, filtres) et règles de l'aide CM360 (date jamais en filtre, pas de pivot multiple, programmation « Schedule and delivery » à minuit, pièce jointe ≤ 25 Mo, désactivation après 60 jours sans téléchargement ou 30 jours d'échec). Moteur : `web/cm_prompt.js`, testé par `node tests/cm_prompt_check.mjs`.
- **Connexion des ad servers** (secrets du Worker, jamais dans la page) : CM360 → `CM360_SA_JSON` (JSON du compte de service ayant accès au profil) et `CM360_PROFILE_ID` ; Adform → `ADFORM_CLIENT_ID` et `ADFORM_CLIENT_SECRET` (endpoints Adform **à valider avec un accès réel**). Sans secret : **données de démonstration** (`web/demo_adserver.json`), signalées dans l'interface ; aucun e-mail n'est envoyé.
- Templates de l'agence : les mises en forme actuelles (colonnes, onglets) sont un point de départ — à aligner sur les templates existants de l'agence.

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

- `node tests/worker_cm360.mjs` : Worker + faux CM360 (jeton RS256, lecture annonceurs / campagnes / emplacements, rapport CSV asynchrone, programmation, pause / modification / suppression d'un report régie, diagnostic, carnet d'adresses).

```bash
pip install -r requirements-dev.txt
python -m pytest -q tests        # le test navigateur est ignoré si Chromium est absent
```

## État et reste à faire

Validés en local (mock) : trafficking, reporting, UI, MCP. **Non validés faute d'accès réel** : CM360 (clé de compte de service) et les statuts/colonnes de l'API Reports (`mediaCost` → colonne « Media Cost »). Types CM360 `TRACKING_TEXT`, `INSTREAM_VIDEO` et `AD_SERVING_TRACKING` : corps de requête testés avec un service factice, **à valider sur un vrai compte**. Adform : authentification et diagnostic seulement, création d'objets à écrire avec un accès réel. Pas implémentés : HTML5, Floodlight, agent d'ingestion IA, multi-agences, déploiement SaaS.
