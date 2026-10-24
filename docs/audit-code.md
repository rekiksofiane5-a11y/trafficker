# Audit du code Agopis — 24/10/2026

Périmètre : tout le dépôt depuis le premier commit (69 commits, 21/10 → 24/10/2026). Objectif : nettoyer, solidifier, et préparer la réécriture des specs. Aucune modification de code dans ce lot.

## 1. État des lieux en chiffres

| Bloc | Fichiers | Lignes | Rôle |
|---|---|---|---|
| Page web | `web/index.html` | 4 838 (568 CSS + ~4 200 JS, 181 fonctions, 78 variables globales, 191 écouteurs) | Toute l'interface : trafficking, reporting, croisé, réglages, surveillance, cloche, assistant |
| Modules web | `quality.js`, `pivot.js`, `cm_prompt.js`, `grid.js`, `engine.js`, `assistant_guide.js` | ~1 100 | Logique isolée et testée en Node |
| Worker | `worker.js`, `adserver.js` | 847 | Comptes, tâches, réglages, API CM360/Adform, URL, surveillance, assistant |
| Moteur Python (navigateur via Pyodide) | `cm360_trafficker.py`, `plan_agent.py`, `agency_sheet.py`, `ingest.py`, `reporting.py`, `creative_specs.py`, `cm360_bulk.py`, `adform_bulk.py`, `web/web_api.py` | ~5 600 | Lecture des PM, nomenclature, contrôles, exports, reporting |
| Ancienne version serveur | `cm360_trafficker_ui.py`, `trafficker_store.py`, `cm360_reporting.py`, `cm360_mcp_server.py`, `cm360_ui_demo.html`, `Dockerfile`, `Caddyfile`, `docker-compose.yml`, `wrangler.containers.jsonc`, `cloudflare/worker.js`, workflow `deploy-cloudflare` | ~2 400 | UI Flask, SQLite, MCP, conteneur Cloudflare payant |
| Tests | 23 fichiers Python + 4 Node | ~3 900 | 250 tests en ~2 min, tous verts |

Lint Python (ruff, règles F/B) : 23 alertes, dont 11 imports inutilisés ; 414 corrections automatiques de style (annotations `List`/`Optional` d'ancienne syntaxe). Aucun linter JavaScript. Aucune configuration de lint dans le dépôt.

## 2. Constats prioritaires

### P0 — Sécurité et intégrité des données (à traiter avant d'ouvrir à plusieurs agences)

1. **Cloisonnement entre agences incomplet** (`web/worker.js`) :
   - `GET /api/users` renvoie les comptes **de toutes les agences** à n'importe quel admin ;
   - `POST /api/users` laisse un admin créer un compte (admin compris) **dans une autre agence** ;
   - `DELETE /api/users/:id` supprime un compte **de n'importe quelle agence**.
   Sans conséquence tant qu'une seule agence utilise l'instance ; bloquant dès la deuxième. Il faut un rôle « super-admin Agopis » distinct de « admin d'agence ».
2. **Réglages d'agence écrits en entier par le navigateur, sans contrôle fin** : `requests`, `alerts`, `monitors`, `corrections` sont des blocs JSON remplacés d'un coup par `PUT /api/settings/:clé`.
   - N'importe quel utilisateur de l'agence peut effacer toutes les corrections retenues ou toutes les campagnes surveillées (l'interface le cache, l'API le permet).
   - Deux personnes qui écrivent en même temps s'écrasent (lecture → modification → écriture complète). Cas réel : une alerte calculée par le Worker et une saisie de chiffres régie au même moment.
   - Aucun schéma : une valeur mal formée casse l'écran de toute l'agence.
   → Passer ces données en **tables D1** (`monitors`, `alerts`, `requests`, `corrections`, `client_rules`) avec des routes dédiées (ajouter, modifier, supprimer une ligne) et les droits vérifiés côté Worker.
3. **Mot de passe : 10 000 itérations PBKDF2** (choisi pour l'offre gratuite). Faible face aux recommandations actuelles (≥ 600 000). À relever (offre Workers payante) ou à compenser par une connexion via Cloudflare Access / SSO.
4. **Le déploiement n'attend pas les tests** : Workers Builds publie chaque push sur `main`, en parallèle du workflow de tests GitHub. Un push rouge part en production.

### P1 — Architecture

5. **Deux produits dans le même dépôt.** La version utilisée (navigateur + Worker) et l'ancienne version serveur (Flask, SQLite, MCP, conteneur) coexistent ; l'ancienne représente ~2 400 lignes, 4 fichiers de tests et un workflow de déploiement.
   - La version serveur est la **seule qui sait créer réellement** les campagnes dans CM360/Adform (adaptateurs `CM360Adapter` / `AdformAdapter` de `cm360_trafficker.py`, via `google-api-python-client`). La version web exporte des classeurs à importer à la main.
   - Deux moteurs de reporting : `cm360_reporting.py` (ancien, encore appelé par `web_api.delivery_demo`) et `reporting.py` (actuel).
   → **Décision de spec** : objectif « tout via API » = porter l'écriture CM360/Adform dans le Worker (JavaScript, comme la lecture dans `adserver.js`) puis retirer la version serveur ; ou garder un service Python dédié au trafficking réel. Le serveur MCP est à garder seulement s'il a un usage prévu.
6. **`web/index.html` monolithique** (4 800 lignes, état global partagé : `current`, `table`, `columns`, `RP`, `MEM`…). Chaque lot ajoute au même fichier ; les régressions croisées deviennent probables (ex. deux fonctions `startRename` homonymes, trouvé lors du renommage des tâches).
   → Découper en modules ES servis tels quels (pas de bundler nécessaire, la CSP autorise `'self'`) : `store.js`, `trafficking.js`, `preview.js`, `reporting.js`, `pivot-ui.js`, `agency-settings.js`, `notifications.js`, `assistant.js`, `styles.css`.
7. **`cm360_trafficker.py` fourre-tout** (1 736 lignes : CLI, modèle du plan, chargement, validation, nomenclature, adaptateurs, export). → `model.py`, `loaders.py`, `naming.py`, `validation.py`, `adapters/`.
8. **Quatre chemins de lecture d'un PM** choisis dans `load_rows_from_path` (trafficking sheet d'agence, cases jaunes, colonnes canoniques, extraction libre). Ils fonctionnent mais leur priorité et leurs différences ne sont écrites nulle part. → À documenter dans les specs (un tableau « type de fichier → lecteur → ce qui est lu »).
9. **Mode local** (sans Worker, données dans le navigateur) : 27 branches `Store.local` dans la page. Utile pour les tests, mais plusieurs fonctions y sont désactivées (URL, assistant, e-mails) et ne sont donc testées que par le test Worker. → Décider s'il reste un mode produit ou devient un simple outil de test.

### P2 — Qualité du code

10. **Fonctions dupliquées** :
    - normalisation de texte (accents, casse) : `normName`, `normV`, `siteKey` (page), `keyOf` (`quality.js`), `norm` (`pivot.js`, `cm_prompt.js`) ; côté Python, 8 variantes dans 5 modules ;
    - dates : `plan_agent.parse_date`, `ingest.norm_date`, `cm360_bulk.parse_bulk_date`, `reporting._d` ;
    - nombres / montants : `ingest.norm_budget`, `cm360_bulk._num`, `reporting._num`, `reporting._num_cell`, `web_api._num_fr`, `quality.num`.
    → Un module utilitaire par langage (`web/util.js`, `textutil.py`), testé une fois.
11. **Nettoyage simple** : 11 imports inutilisés, 3 variables de boucle inutilisées, une valeur dupliquée dans un ensemble (`reporting.py:718`, `"VIDEOAD"`), annotations d'ancienne syntaxe ; `cm360_ui_demo.html` sans usage.
12. **État global du moteur Python** (`web_api._STATE`) : un seul plan à la fois, effacé par `restore`. Fragile si deux traitements se croisent (analyse + rythme de diffusion d'une autre tâche).
13. **Points d'accroche de test par variables globales** (`window.assistantAsk` remplacé dans les tests) : acceptable aujourd'hui, à remplacer par l'injection propre au découpage en modules.
14. **Le mode d'emploi de l'assistant** (`web/assistant_guide.js`) se met à jour à la main : il dérivera de l'interface. → Le générer à partir des specs, ou ajouter un test qui vérifie que les libellés de boutons cités existent dans la page.

### P3 — Tests et intégration continue

15. **Tests navigateur dépendants de l'ordre** : `tests/test_web.py` partage une seule page pour 35 tests. Un test lancé seul peut échouer (constaté : choix de l'ad server avant l'import). → Une page neuve par test ou par groupe, avec stockage vidé.
16. **Tests dépendants de la date du jour** : l'export CM360 a cassé le jour où la date a changé (calendrier de report). → Figer l'heure dans les tests (horloge simulée de Playwright côté page, `now` injecté côté Python et JS).
17. **Le test du Worker n'est pas dans l'intégration continue** (`tests/worker_cm360.mjs`, il lance `wrangler dev`). C'est le seul qui couvre les comptes, les droits, CM360, la surveillance programmée, l'e-mail et l'assistant. → L'ajouter au workflow `tests`.
18. **Pas de lint en CI** (ruff pour Python, ESLint pour JS) ni de mesure de couverture.

### P4 — Documentation

19. **README trop dense et en partie périmé** (ex. « ＋ Nouvelle tâche » et « Historique repliable à droite », remplacés depuis). Il mêle installation serveur, version web, specs fonctionnelles et réglages.
    → Séparer : `README.md` (démarrage et déploiement), `docs/specs/*.md` (une page par fonction : lecture PM, nomenclature, contrôles, reporting, surveillance, réglages, assistant), `docs/exploitation.md` (secrets, déclencheurs, coûts).
20. **Noms hérités** : « Trafficker » (Worker, secrets, modules `cm360_*` qui gèrent aussi Adform) à côté d'« Agopis ». À trancher une fois, au moment du découpage.

## 3. Décisions à prendre dans les specs

| Sujet | Options | Recommandation |
|---|---|---|
| Version serveur (Flask, MCP, conteneur) | Garder / retirer | Retirer après avoir porté l'écriture CM360/Adform dans le Worker |
| Trafficking réel par API | Worker JS / service Python | Worker JS : un seul socle, mêmes secrets que la lecture |
| Agences multiples sur une instance | Oui / non | Oui → rôle super-admin et cloisonnement (P0-1) d'abord |
| Stockage des réglages vivants | JSON par clé / tables | Tables pour tout ce qui est modifié par plusieurs personnes |
| Mode local | Produit / outil de test | Outil de test |
| Templates de reporting | Formats actuels / formats de l'agence | Aligner sur les modèles Excel réels de l'agence |
| Démo | Données relatives au jour / jeu figé | Jeu figé pour les tests, relatif pour la démo commerciale |

## 4. Plan de nettoyage proposé (un lot = un commit)

1. **Lot 0 — sans risque** : imports inutilisés, `cm360_ui_demo.html`, valeur dupliquée, configuration ruff + ESLint, lint en CI, test Worker en CI, README corrigé sur les points périmés.
2. **Lot 1 — sécurité** : cloisonnement des comptes par agence (super-admin), droits par route sur les réglages, déploiement conditionné aux tests.
3. **Lot 2 — données** : tables D1 pour surveillance, alertes, demandes, corrections, règles client ; migration des valeurs existantes.
4. **Lot 3 — tests** : une page par test, horloge figée, jeu de démo figé.
5. **Lot 4 — page web** : découpage de `index.html` en modules, utilitaires communs.
6. **Lot 5 — moteur Python** : découpage de `cm360_trafficker.py`, utilitaires dates / nombres / texte, retrait de `cm360_reporting.py` côté web.
7. **Lot 6 — selon les specs** : écriture CM360/Adform dans le Worker, puis retrait de la version serveur.

Chaque lot garde les 250 tests verts et ajoute ceux qui manquent.
