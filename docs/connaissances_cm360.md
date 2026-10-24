# Connaissances CM360 apprises par Agopis

Règles appliquées par l'agent (contrôles « Avant l'import dans CM360 », fiche de création, prompt de rapport).
Source de chaque règle entre parenthèses ; « constaté » = vérifié sur un vrai compte.

## Campagne (aide « Configurer une campagne », answer/2838056)
- Nom : moins de 512 caractères, unique chez l'annonceur.
- Dates : fin ≥ début ; une nouvelle campagne ne peut pas commencer dans le passé (une copie aux dates passées est recalée sur aujourd'hui, fin à +30 jours si elle aussi est passée).
- Page de destination par défaut : obligatoire (page de l'annonceur).
- Code de facturation : 64 caractères max, figure sur la facture ; traité le 1er du mois.
- ID externe : 50 caractères max, lettres, chiffres, « - » et « _ » ; champ parfois désactivé selon le compte.
- Commentaires : 255 caractères max.
- Publicité politique UE : à déclarer (contient / ne contient pas).
- Dates d'emplacement : informatives pour le reporting, n'arrêtent pas la diffusion ; les dates d'annonce peuvent dépasser la fin de campagne.

## Import du Campaign spreadsheet
- Sans Site ID ni nom de site existant, CM360 ne crée ni emplacement, ni annonce, ni assignation : seules les créatives sont importées (constaté).
- Site ID prioritaire sur le nom ; le nom doit être exactement celui du site dans CM360.
- Placement ID vide = création d'un emplacement.
- Packages (Group ID / Group type) : format à confirmer sur un export rempli.

## Rapports (aide « Instant reporting », answer/7674615)
- Report builder → Instant reporting → New ; « Generate report » (bêta) accepte une demande en langage naturel.
- La date est une colonne, jamais un filtre : la période se règle dans « Date range ».
- Pivot : téléchargement seul ; plusieurs métriques pivotées empêchent l'exécution → rester en « Flat table ».
- Rapport trop lourd : réduire la période ou les dimensions, ou « Download ».
- Programmation : « Schedule and delivery » → Schedule status, fuseau, fréquence, période ; envoi à minuit dans le fuseau ; Delivery : Attachment (≤ 25 Mo) ou Link to report, Email owner, Add people.
- Désactivation : rapport programmé non téléchargé depuis 60 jours ou en échec depuis 30 jours ; arrêt si le propriétaire devient inactif ou perd ses droits.

## Exports réels (constaté sur un export Instant reporting, compte agence)
- L'Excel téléchargé n'est pas un .xlsx standard (workbook.xml à la racine, feuille `xl/worksheets/data.xml`, styles incomplets) : Excel l'ouvre, mais openpyxl échoue → Agopis le lit directement par son XML.
- Bloc d'en-tête : Date/Time Generated, Report Time Zone, Account ID, Date Range, mention « Reporting numbers are finalized after seven days », puis « Report Fields » / « Report Metrics », colonnes, et « Grand Total: ».
- « Generate report » peut ignorer le filtre campagne donné par son nom et exporter tout le compte : le prompt d'Agopis impose maintenant « Campaign ID = … », ajoute Campaign et Campaign ID en colonnes et rappelle de vérifier « Filter » avant « Run report ».
- Nombreux emplacements 1x1 avec des clics sans impression (click trackers, diffusion achetée en DSP) : comptés comme « données reçues ».
- La colonne Site (CM360) contient souvent la plateforme d'achat (The Trade Desk, AMNET, BidManager_DfaSite = DV360) ; l'éditeur est dans le nom d'emplacement (ex. R-NOTORIETE-CPM-LEMONDE--CUSTOM-LeMonde-GRANDANGLE-1x1-Multidevice-NA).

