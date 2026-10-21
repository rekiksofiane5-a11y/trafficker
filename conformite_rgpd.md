
# Conformité RGPD — CM360 Trafficker

Document de conformité de l'outil de génération de trafficking à partir d'un plan média (CSV/XLSX/Google Sheets). À conserver à jour et à compléter avec les informations de l'entité éditrice dès la mise en production.

## 1. Rôles

| Acteur | Rôle RGPD |
|---|---|
| Éditeur de l'outil (aujourd'hui : projet personnel ; demain : la société) | **Responsable de traitement** des données uploadées dans l'outil |
| Client / agence utilisatrice | Fournit le plan média ; reste responsable de la donnée de son côté |
| Google (Campaign Manager 360, Sheets) | **Sous-traitant** pour CM360 (Google Ads Data Processing Terms applicables) ; responsable pour Sheets |
| Adform | **Sous-traitant** (DPA à obtenir avec le compte client) |
| Mistral AI (option `--llm` de l'agent d'ingestion) | **Sous-traitant** pour l'extraction IA (DPA public conforme RGPD) |

## 2. Registre des traitements

| # | Finalité | Données traitées | Données personnelles ? | Base légale | Conservation |
|---|---|---|---|---|---|
| T1 | Lecture du plan média (fichier, XLSX ou Google Sheets) | Noms annonceurs/campagnes/placements, sites, formats, dates, tags, URLs de destination | Aucune requise ; contacts possibles dans les plans clients → à proscrire | Art. 6.1.b — exécution du contrat | Traitement immédiat ; export Sheets supprimé après lecture |
| T2 | Upload des créatives IMAGE (dossier ou ZIP) | Fichiers images, noms de fichiers | Non | Art. 6.1.b | Supprimées dès la fin du job (ZIP décompressé côté serveur purgé) |
| T3 | Génération du trafficking via l'API de la plateforme | Objets publicitaires (mêmes données que T1/T2) | Non | Art. 6.1.b | Les objets vivent dans la plateforme cible (CM360/Adform), pas dans l'outil |
| T4 | Rapport JSON (redevabilité, traçabilité) | IDs et noms des objets créés/réutilisés | Non | Art. 6.1.b et intérêt légitime (preuve de livraison) | ≤ 1 h côté serveur ; le client le télécharge et l'archive chez lui |
| T5 (option) | Extraction IA du plan (agent d'ingestion, `--llm`) | Contenu du plan média envoyé à l'API Mistral | Idem T1 — anonymiser avant envoi | Art. 6.1.b + garantie contractuelle (DPA Mistral : pas d'entraînement sur les données API) | Selon la politique de rétention API du fournisseur |
| T6 | Logs d'exécution | Messages techniques (noms d'objets, codes erreur) ; **jamais de secrets** | Non | Intérêt légitime (sécurité, debug) | ≤ 1 h côté serveur (mémoire), purgés avec le job |

## 3. Mesures techniques (art. 32)

- **Minimisation** : aucune donnée personnelle n'est nécessaire au fonctionnement ; les plans clients ne doivent pas contenir d'emails / noms de contacts.
- **Purge automatique** : export Google Sheet supprimé immédiatement après lecture (CLI) ; créatives extraites du ZIP supprimées à la fin du job ; jobs, plans et rapports supprimés au plus tard **1 h** après création (filet de sécurité).
- **Secrets** : clés et identifiants passés par variables d'environnement ou champs dédiés ; champ mot de passe + `autocomplete=off` pour le secret Adform ; jamais journalisés ; jamais versionnés (git-ignore sur la clé JSON).
- **Traçabilité** : rapport JSON téléchargeable (preuve de livraison).
- **Périmètre des flux** : les données du plan ne sont envoyées qu'à la plateforme cible choisie ; l'outil n'appelle aucun autre service (hors option `--llm` explicite).
- À mettre en place en production : HTTPS obligatoire (reverse proxy), authentification des utilisateurs de l'UI, chiffrement disque de l'hébergeur, sauvegardes chiffrées.

## 4. Droits des personnes

Les traitements portent sur des données publicitaires B2B, sans donnée personnelle requise : le risque d'exercice de droits (accès, rectification, effacement, opposition) est très faible. Si l'outil devient SaaS : prévoir une adresse de contact DPO/privacy dans les CGU et un canal de traitement des demandes sous 30 jours.

## 5. AIPD (analyse d'impact)

Non requise a priori : pas de suivi à grande échelle, pas de données sensibles (art. 9), pas de profilage par l'outil lui-même. **Point de vigilance** : si l'outil venait à ingérer des données d'audience / performance (cookies, identifiants publicitaires) ou à se connecter aux APIs de reporting, une réévaluation serait nécessaire. Rappel : le tracking côté sites (consentement utilisateurs finaux, CMP, signaux de consentement Google) reste à la charge des annonceurs/agences, hors périmètre de l'outil.

## 6. Références

- Google Ads Data Processing Terms (couvrent Campaign Manager 360) : https://business.safety.google/adsservices/
- DPA Mistral AI (Data Processing Addendum) : https://legal.mistral.ai/terms/data-processing-addendum/
- RGPD : règlement (UE) 2016/679, art. 6, 9, 28, 30 (registre), 32 (sécurité), 35 (AIPD)


## 7. Mise à jour v2 — persistance SQLite et authentification

- L'UI enregistre l'état des jobs (libellé, journal, rapport, lignes du plan) dans une base SQLite locale (`TRAFFICKER_DB`). **Aucun secret** (clé de compte de service, secret OAuth Adform) n'y est écrit.
- Rétention : suppression automatique après 1 heure, comme les jobs en mémoire (`purge`).
- Authentification optionnelle par mot de passe haché (werkzeug), session HTTP-only, blocage après 5 échecs en 5 minutes.
