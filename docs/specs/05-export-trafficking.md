# 05 — Export et trafficking

## Aujourd'hui
- **Version web (utilisée)** : export du **Campaign spreadsheet CM360** (Bulk Editor) et du **classeur bulk Adform**, à importer à la main ; trafficking et diffusion simulés.
- **Ancienne version serveur** (Flask, CLI, MCP) : création réelle dans CM360 et Adform par API (adaptateurs Python).
- Lecture par API dans le Worker : annonceurs, campagnes, emplacements, sites, diffusion, reports programmés (CM360 ; Adform à valider avec un accès réel).

## Cible (« tout via API »)
1. « Créer dans CM360 » / « Créer dans Adform » depuis la carte « prêt », après validation des deux étapes et sans bloquant.
2. Création dans l'ordre campagne → sites / packages → emplacements → créatives → annonces, avec reprise si une étape échoue et journal dans la tâche.
3. Retour des ID créés dans le plan (colonne ID) ; contrôle des URL et des tags après création.

## À trancher
- **D1** : écriture API dans le Worker (JavaScript, mêmes secrets que la lecture) ou service Python dédié. Recommandation : Worker.
- **D2** : retrait de l'ancienne version serveur une fois D1 livré.
- Droits : qui peut créer en production (admin seulement ? validation à deux ?).
