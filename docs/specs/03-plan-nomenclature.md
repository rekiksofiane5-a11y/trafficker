# 03 — Plan classé et nomenclature

## Structure
1 PM = 1 annonceur = 1 campagne → objectifs → régies (sites de l'ad server) → emplacements (format × ciblage × devices) → annonces → créatives.

## Écran
- Carte « Votre PM est prêt » : emplacements, annonces / créatives, points à vérifier ; choix de l'ad server ; export.
- « Plan média classé par Umnia » : plan modifiable à gauche (cases orange à compléter, édition en masse), aperçu tel que dans l'ad server à droite (CM360 : Campagne > Site > Package > Emplacement > Annonce > Créative ; Adform : campagne, line items, bannières, tags).
- Validation en deux étapes : « Valider les emplacements », puis annonces et créatives.
- Aperçu : double-clic = renommer (nom imposé, prioritaire sur la nomenclature), glisser-déposer, « Créer un package avec la sélection ».

## Nomenclature
| Source | Règle |
|---|---|
| Trafficking sheet d'agence | Gabarit du classeur (formules) |
| Fichier de nomenclature joint | Gabarits du fichier |
| Par défaut | Emplacement `OBJECTIF-AUDIENCE-RÉGIE-CIBLAGE-FORMAT`, créative `RÉGIE-FORMAT-MESSAGE`, annonce = emplacement-créative |
- Majuscules sans accents, espaces → `_`, segments absents sautés, homonymes suffixés `-2`.
- Package par défaut : `PACKAGE-RÉGIE-OBJECTIF-CIBLAGE`, un par ciblage.
- Régies : nom exact du site de l'ad server repris (répertoire par API, sinon démo).
- Formats IAB reconnus (Pavé → 300x250…) ; vidéo in-stream ; sinon tracking 1x1 ; VAST → 0x0.

## À trancher
- Nomenclatures par client gérées dans les réglages (aujourd'hui : classeur ou fichier joint).
- Règles de longueur maximale par segment selon l'ad server.
