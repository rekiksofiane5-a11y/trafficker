# 04 — Contrôles avant mise en ligne

Affichés dans « Points à vérifier » (rouge = bloquant, orange = à vérifier, « i » = information). L'export attend la correction des bloquants.

| Famille | Contrôles | Niveau |
|---|---|---|
| Informations manquantes | Dates, URL, champs obligatoires (cases orange) | À vérifier (bloquant pour l'envoi par API) |
| CM360 | Politique UE, début dans le passé, champs de campagne | Selon CM360 |
| Créatives | Specs officielles CM360 (poids, dimensions, durée, HTML5…) si fichiers joints | Erreur = bloquant |
| Régies | Site introuvable dans l'ad server (suggestions) | Bloquant avec API, à vérifier en démo |
| URL de destination | Erreur HTTP, pas de réponse en 8 s, redirection vers un autre domaine (vérifiées par le Worker, en ligne) | Bloquant / à vérifier |
| UTM | Absentes sur certaines lignes, incomplètes, répétées, `utm_campaign` multiple, même valeur écrite de plusieurs façons, espaces, `utm_source` multiple par régie ou partagé entre régies, http | À vérifier |
| Budgets / volumes | CPM implicite atypique (×3 / ÷3 de la médiane), budget sans volume, volume sans budget, somme des lignes ≠ budget campagne | À vérifier |
| Règles du client | Voir 06 | Selon la règle |
| Mémoire | Corrections de l'agence appliquées | Information |

## À trancher
- Contrôle des URL des créatives déjà en ligne dans l'ad server (après création).
- Niveaux par défaut (ex. UTM absentes bloquant pour certains clients → règle client).
