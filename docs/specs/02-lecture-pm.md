# 02 — Lecture du PM

## Objectif
Lire n'importe quel plan média tel qu'il arrive, sans ressaisie, et dire d'où vient chaque information.

## Fichiers
CSV (`;` `,` tabulation `|`, UTF-8 ou Windows-1252), XLSX, XLS ; toutes les feuilles ; feuille et ligne d'en-tête trouvées automatiquement. Lecture dans le navigateur : le fichier n'est jamais envoyé.

## Quatre lecteurs, dans cet ordre
| Ordre | Cas reconnu | Lecteur | Ce qui est lu |
|---|---|---|---|
| 1 | Trafficking sheet d'agence (noms construits par formule, onglet de listes) | `agency_sheet.py` | Nomenclature du classeur, vocabulaire, ciblages « #Type : segment », formats précis |
| 2 | Cases surlignées en jaune | `plan_agent.extract` (mode jaune) | Uniquement les cases jaunes + libellés |
| 3 | Export « Campaign spreadsheet » CM360 | `cm360_bulk` | Plan reconstruit depuis l'export |
| 4 | Colonnes canoniques | `ingest` | Colonnes standard (gabarit Agopis) |
| 5 | Tout autre PM | `plan_agent.extract` | En-têtes (synonymes FR/EN), puis contenu des colonnes, bloc d'informations au-dessus du tableau |

## Règles
- Rien n'est inventé : information introuvable = case vide « à compléter ».
- Bloc au-dessus du tableau (Client, Campagne, Période, Objectif général, Budget, URL…) appliqué à toutes les lignes.
- Cellules fusionnées complétées, lignes de total ignorées, périodes en toutes lettres découpées.
- Plusieurs formats ou ciblages dans une cellule : une ligne par combinaison.
- Instructions supplémentaires « Clé : valeur » (campagne, annonceur, début, fin, période, URL, régie, objectif, audience, ciblage, devices, package) ; les autres sont notées « non interprétées ».
- Rapport de lecture (provenance) replié sous « Détails de l'analyse ».

## Mesure de qualité
Banc d'essai sur PM réels avec fiche attendue : MEAE 22/25 emplacements identiques (créas 90/90), DICOM ex2 44/60, ex3 7/7.

## À trancher
- Banc d'essai élargi (10 à 20 PM réels) et objectif chiffré par type de PM.
- Lecture des PDF (aujourd'hui non pris en charge).
