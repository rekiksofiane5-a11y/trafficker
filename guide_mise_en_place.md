
# CM360 Trafficker — Guide de mise en place

Outil qui génère le trafficking d'une campagne **Campaign Manager 360** (API v5) à partir d'un plan média CSV/XLSX : annonceur → landing page → campagne → emplacements → créatives → annonces (rotation + affectation des placements).

## 1. Architecture

- **Moteur** (`cm360_trafficker.py`) : lecture du plan média, validation, puis trafficking via des **adaptateurs interchangeables** derrière l'interface `TraffickingAdapter` :
  - `CM360Adapter` — Campaign Manager 360 (API v5, compte de service Google) ;
  - `AdformAdapter` — Adform (OAuth 2.0 et diagnostic `--check` prêts ; création d'objets à compléter à l'obtention d'un accès réel) ;
  - `MockAdapter` — mode démo simulé, aucun accès requis.
  L'orchestrateur et le plan média sont strictement identiques pour toutes les plateformes : ajouter une plateforme = écrire un nouvel adaptateur.
- **Interface web** (`cm360_trafficker_ui.py`, Flask) : interface **conversationnelle** (style ChatGPT) — plan média joint via 📎 ou URL Google Sheets collée dans la zone de saisie, aperçu et nomenclatures affichés dans la conversation, validation puis exécution avec logs en direct, rapport JSON téléchargeable, sidebar des exécutions récentes ; réglages ⚙️ (plateforme, mode démo, identifiants).
- **Plan média** : un fichier CSV/XLSX (voir le template fourni). Une ligne = une créative dans une annonce ; les lignes partageant le même `ad_name` fusionnent leurs créatives en rotation.

## 2. Prérequis d'accès API (à faire une seule fois)

CM360 exige que l'appelant ait un **profil utilisateur dans le compte CM360 visé**. Le plus simple est un compte de service Google Cloud :

1. **Console Google Cloud** → créer (ou choisir) un projet : https://console.cloud.google.com
2. **Activer la Campaign Manager 360 API** dans ce projet : https://console.cloud.google.com/apis/library/dfareporting.googleapis.com
3. **Créer un compte de service** (IAM & Admin → Comptes de service), puis générer une **clé JSON** (touche "Keys" → Add key → JSON). Conservez ce fichier précieusement : il donne accès à votre compte CM360.
4. **Dans CM360** (avec un compte admin) : Administration → Utilisateurs et rôles → Nouvel utilisateur → coller l'email du compte de service (`xxx@projet.iam.gserviceaccount.com`), lui donner un rôle avec droits de trafficking (ex. *Traqueur avancé* — "Advanced Trafficker") et filtrer sur les annonceurs concernés.
   ⚠️ Sans cette étape, l'API renverra une erreur 403 ou "no user profile" même si la clé est valide.
5. Récupérer le **profil** : le premier appel `userprofiles.list` renvoie le(s) profil(s) disponibles ; notez l'ID (`--profile-id`) si votre compte gère plusieurs comptes CM360.

## 3. Installation

```bash
pip install google-api-python-client google-auth openpyxl
# pour l'interface web :
pip install flask
```

Placer `cm360_trafficker.py`, `cm360_trafficker_ui.py` et le plan média dans le même dossier.

## 4. Utilisation en ligne de commande

```bash
# 0. Démo locale, aucun accès requis
python cm360_trafficker.py plan_media.csv --platform mock

# 1. Validation sans appel API (fortement recommandé au début)
python cm360_trafficker.py plan_media.csv --dry-run

# 2. Diagnostic de l'accès CM360 (profils, annonceurs, sites)
python cm360_trafficker.py --platform cm360 --check --service-account cle.json

# 3. Exécution réelle CM360
python cm360_trafficker.py plan_media.csv --platform cm360 \
    --service-account /chemin/cm360-sa.json \
    --report rapport_trafficking.json

# Créatives IMAGE livrées dans un dossier (les creative_path du plan
# sont relatifs à ce dossier)
python cm360_trafficker.py plan_media.csv --platform cm360 \
    --service-account /chemin/cm360-sa.json --creatives-dir /chemin/creas

# Adform : authentification + diagnostic (création d'objets à compléter avec un accès réel)
python cm360_trafficker.py --platform adform --check \
    --adform-client-id XXX --adform-client-secret YYY

# 4. Avec nomenclatures de nommage (renommage automatique à la vérification,
#    avant l'envoi — les renommages sont listés, rien n'est envoyé avant validation)
python cm360_trafficker.py plan_media.csv --platform mock \
    --nomenclature nomenclatures.json
```

Variables d'environnement possibles : `CM360_SA_KEY` (chemin de la clé JSON), `CM360_PROFILE_ID`, `ADFORM_CLIENT_ID`, `ADFORM_CLIENT_SECRET`.

**Import depuis Google Sheets** : le plan média peut être l'URL d'une feuille partagée en lecture (« tout le monde avec le lien ») ; exportez-la en CSV via `File → Share → Publish to web` (ou passez simplement l'URL du sheet dans l'interface web) :

```bash
python cm360_trafficker.py "https://docs.google.com/spreadsheets/d/…/gviz/tq?tqx=out:csv" --dry-run
```

## 5. Utilisation avec l'interface web (conversationnelle)

```bash
python cm360_trafficker_ui.py
# puis ouvrir http://localhost:5000
```

1. Joindre le plan média (.csv/.xlsx) via 📎, **ou** coller l'URL d'un Google Sheet partagé en lecture dans la zone de saisie
2. En option : nomenclatures de nommage (JSON) et ZIP de créatives IMAGE (📎 → menu)
3. Réglages ⚙️ si besoin : plateforme cible, mode démo (aucun accès requis), clé de compte de service, identifiants Adform
4. L'assistant affiche l'aperçu (campagnes, nomenclatures appliquées, erreurs) ; envoyer ⏎
5. Cliquer **« Lancer le trafficking »** → logs en direct dans la conversation, puis lien **« Télécharger le rapport JSON »**
6. La sidebar garde les exécutions récentes (cliquer pour rejouer les logs / re-télécharger un rapport)

## 6. Règles du plan média

| Colonne | Obligatoire | Notes |
|---|---|---|
| `advertiser_id` ou `advertiser_name` | oui (l'un des deux) | l'annonceur est créé s'il n'existe pas |
| `campaign_name`, `campaign_start`, `campaign_end` | oui | dates au format `YYYY-MM-DD` |
| `placement_name` | oui | un emplacement est créé par nom unique |
| `site_id` ou `site_name` | oui | `site_id` recommandé (recherche par nom plus lente) |
| `size` | oui | format `300x250` |
| `pricing_type` | non | `CPM` (défaut), `CPC`, `CPA`, `FLAT` |
| `ad_name` | oui | les mêmes `ad_name` fusionnent leurs créatives en rotation |
| `creative_name`, `creative_type` | oui | `REDIRECT` (tag tiers) ou `IMAGE` (fichier local) |
| `snippet` | si REDIRECT | le tag tiers complet |
| `creative_path` | si IMAGE | chemin local du fichier sur la machine qui exécute l'outil |
| `landing_page_url` | oui | crée/réutilise la landing page annonceur |
| `active` | non | `1` par défaut |

## 6bis. Nomenclatures de nommage (par annonceur)

Fichier JSON (`--nomenclature` en CLI, champ dédié dans l'UI) appliqué **à la vérification, avant l'envoi** : chaque campagne, emplacement, annonce et créative est renommé selon les conventions de son annonceur, et la liste des renommages est affichée pour validation. Rien n'est envoyé tant que vous n'avez pas cliqué « Lancer le trafficking ».

Structure (voir le template fourni) :

```json
{
  "defaults":   { "campaign": "...", "placement": "...", "ad": "...", "creative": "...", "options": {...} },
  "advertisers": { "Client XYZ": { ...mêmes clés... } }
}
```

- Les règles de l'annonceur (clé = `advertiser_name` ou `advertiser_id`) priment sur `defaults`.
- **Jetons** disponibles dans les motifs : `{advertiser_name}`, `{advertiser_id}`, `{campaign_name}`, `{campaign_start}`, `{campaign_end}`, `{year}`, `{start_yyyymm}`, `{placement_name}`, `{site_name}`, `{site_id}`, `{size}`, `{pricing_type}`, `{ad_name}`, `{creative_name}`, `{creative_type}`. Les jetons inconnus sont simplement supprimés.
- **Options** : `separator` (défaut `_`), `case` (`upper` / `lower` / `title`), `strip_accents` (défaut vrai), `max_length` (tronque), `forbidden` (caractères supprimés). Exemple : `Printemps Été FR` → `PRINTEMPS_ETE_FR`.
- Exemple : `"placement": "XYZ_{campaign_name}_{site_name}_{placement_name}_{size}"` donne, après normalisation (upper + sans accents), `XYZ_PRINTEMPS_2026_FR_MEDIAKIT_HABILLAGE_HP_300X250`.
- Les références placements dans les annonces sont remappées automatiquement après renommage.

## 7. Reporting de diffusion (lecture multi-plateformes)

`cm360_reporting.py` complète le moteur : il **lit** la diffusion sur l'ad server (impressions, clics, CTR par campagne/emplacement) et la **réconcilie avec le plan** (pacing : OK / EN RETARD / EN AVANCE si le plan contient une colonne optionnelle `objective_impressions`).

```bash
pip install google-api-python-client google-auth openpyxl   # + flask pour l'UI, "mcp[cli]<2" pour le serveur MCP

# Démo locale (aucun accès requis)
python cm360_reporting.py plan_media.csv --platform mock

# Rapport réel CM360 (Reports API v5, même compte de service)
python cm360_reporting.py plan_media.csv --platform cm360 \
    --service-account cle.json --profile-id 1234567

# Sortie JSON (pour dashboard / IA)
python cm360_reporting.py plan_media.csv --platform mock --json rapport.json
```

## 8. Serveur MCP — le moteur utilisable depuis n'importe quelle IA

`cm360_mcp_server.py` expose le produit en **serveur MCP** (Model Context Protocol) : c'est la réponse au mouvement « agentic » des ad servers (Adform a ouvert FLOW via MCP ; Google annonce REST APIs + MCP pour le trafficking). Votre IA d'agence (Vibe, ChatGPT, Claude, Copilot, agent interne) pilote alors le trafficking en langage naturel : analyse du plan, nomenclatures, lancement, rapport de diffusion.

```bash
pip install "mcp[cli]<2"
python cm360_mcp_server.py        # serveur stdio
```

Configuration dans un client MCP (ex. Claude Desktop, Cursor, agent interne) :
```json
"mcpServers": {
  "cm360-trafficker": {
    "command": "python",
    "args": ["/chemin/vers/cm360_mcp_server.py"]
  }
}
```

Outils exposés : `analyze_plan` (validation + nomenclatures), `traffic` (exécution mock/réelle, rapport JSON), `check_access` (diagnostic), `report_delivery` (diffusion + pacing). Sécurité : `traffic` exige `platform="mock"` ou des identifiants explicites — aucune écriture réelle par accident.

## 9. Points d'attention

- **API v5 obligatoire** : la v4 de la Campaign Manager 360 API est obsolète depuis février 2026 — n'utilisez pas les vieux exemples `v4` trouvés en ligne.
- **Créatives REDIRECT recommandées** pour un trafficking d'agence (tags tiers) ; le type IMAGE nécessite les fichiers sur la machine qui exécute l'outil — fournissez-les via `--creatives-dir` (CLI) ou le ZIP dans l'interface web, avec des `creative_path` relatifs dans le plan.
- **Google Sheets** : la feuille doit être partagée « tout le monde avec le lien » en lecture ; l'outil en télécharge l'export CSV. Aucune authentification nécessaire.
- **Ordre imposé par l'API** : une créative doit être associée à la campagne (`campaignCreativeAssociations`) *avant* d'être rattachée à une annonce — le moteur gère cet ordre automatiquement.
- **Idempotence** : les objets existants (même nom) sont réutilisés, pas dupliqués → vous pouvez relancer le même plan sans risque.
- **Quotas** : l'API limite le nombre de requêtes/seconde ; le moteur fait des retries automatiques, mais pour de très gros plans, espacez les campagnes.
- **Comportement type par défaut** : les dates/heures des placements héritent de la campagne ; les tarifs négociés (rate card) se gèrent dans CM360 ou via les champs pricing de l'API si besoin d'aller plus loin.
- **Ne jamais versionner la clé JSON** du compte de service (git-ignore) ; restreindre son rôle CM360 au strict nécessaire.
- **RGPD** : aucune donnée personnelle n'est requise dans le plan média ; purge automatique des fichiers temporaires (export Sheets supprimé après lecture côté CLI ; créatives du ZIP supprimées à la fin du job ; jobs et rapports UI conservés au plus 1 h). Registre des traitements, rôles et sous-traitants : voir le document « Conformité RGPD ».

## 10. Dépannage rapide

| Symptôme | Cause probable | Correctif |
|---|---|---|
| 403 / "user does not have access" | le compte de service n'est pas ajouté comme utilisateur CM360 | étape 4 du §2 |
| "no user profile found" | le compte de service n'a accès à aucun compte CM360 | vérifier rôle + filtres annonceurs |
| Erreur `12043` sur l'annonce | créative non associée à la campagne | le moteur le fait ; vérifier sa version à jour |
| 429 répétés | quota dépassé | espacer les exécutions, activer les retries (défaut) |
| Placement en échec | `site_id`/`site_name` invalide | vérifier l'ID dans CM360 (Propriétés du site) |

## 11. Références

- API CM360 (REST v5) : https://developers.google.com/doubleclick-advertisers/rest
- Aperçu du trafficking : https://developers.google.com/doubleclick-advertisers/guides/trafficking_overview
- Tâches de trafficking courantes : https://developers.google.com/doubleclick-advertisers/trafficking_tasks
- Comptes de service : https://developers.google.com/doubleclick-advertisers/service_accounts
- Premiers pas : https://developers.google.com/doubleclick-advertisers/getting_started



## 12. Compléments (v2)

- **Colonnes optionnelles du plan** : `objective_impressions` (pacing impressions) et `budget_eur` (pacing dépense). La dépense lue sur CM360 vient de la métrique `mediaCost` (colonne « Media Cost » du CSV) — à valider avec un accès réel.
- **Rapport de diffusion dans l'UI** : après un trafficking, bouton « 📊 Rapport de diffusion » (même plateforme que le job ; en mode démo : données simulées).
- **Authentification et persistance** : voir `README.md` (variables `TRAFFICKER_PASSWORD_HASH`, `TRAFFICKER_USER`, `TRAFFICKER_SECRET_KEY`, `TRAFFICKER_DB`).
- **Validation renforcée** : dates réelles, fin ≥ début, cohérence des dates entre lignes, doublons de créatives.
- **Tests** : `python -m pytest -q tests`.
