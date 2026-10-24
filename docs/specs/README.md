# Specs Agopis

Une page par fonction. Chaque page décrit **ce que fait le produit aujourd'hui** (référence pour les tests et l'assistant d'aide) et liste **ce qui reste à trancher**. Ordre de lecture conseillé : 01 → 10.

| # | Page | Périmètre |
|---|---|---|
| 01 | [Comptes et agences](01-comptes-agences.md) | Connexion, rôles, cloisonnement |
| 02 | [Lecture du PM](02-lecture-pm.md) | Fichiers acceptés, quatre lecteurs, instructions |
| 03 | [Plan classé et nomenclature](03-plan-nomenclature.md) | Structure, emplacements, packages, noms |
| 04 | [Contrôles avant mise en ligne](04-controles.md) | Points à vérifier, bloquant / à vérifier |
| 05 | [Export et trafficking](05-export-trafficking.md) | Classeurs CM360 / Adform, création par API |
| 06 | [Mémoire de l'agence](06-memoire-regles.md) | Corrections retenues, règles par client, réglages |
| 07 | [Reporting](07-reporting.md) | Annonceur, templates, check, reports régies, croisé |
| 08 | [Surveillance et alertes](08-surveillance.md) | Seuils, cloche, e-mail |
| 09 | [Assistant d'aide](09-assistant.md) | Périmètre, données envoyées, coût |
| 10 | [Exploitation](10-exploitation.md) | Secrets, déclencheurs, déploiement, coûts |

## Décisions ouvertes (issues de l'audit, `docs/audit-code.md`)

| # | Décision | Recommandation | Page |
|---|---|---|---|
| D1 | Création des campagnes par API : Worker (JS) ou service Python | Worker | 05 |
| D2 | Retrait de l'ancienne version serveur (Flask, MCP, conteneur) | Après D1 | 05, 10 |
| D3 | Plusieurs agences sur une même instance | Oui (cloisonnement livré au Lot 1) | 01 |
| D4 | Mode local : produit ou outil de test | Outil de test | 10 |
| D5 | Templates Excel du reporting : alignés sur les modèles de l'agence | Oui, fournir les modèles | 07 |
| D6 | Seuils d'alerte par défaut | À valider | 08 |
| D7 | Fournisseur d'e-mail (Resend) | À valider | 08, 10 |

## Conventions
- Vocabulaire de l'interface : français, vouvoiement ; boutons cités entre « ».
- Ad servers : CM360 et Adform uniquement.
- « Bloquant » empêche l'export ; « À vérifier » informe.
- Toute évolution d'une page ici se reflète dans `web/assistant_guide.js` (mode d'emploi de l'assistant).
