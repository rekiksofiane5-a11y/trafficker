# 08 — Surveillance et alertes

## Parcours
Check de mise en ligne → « Surveiller cette campagne » (destinataires de l'agence) → alertes dans le check, la cloche et par e-mail → « Arrêter la surveillance ».

## Alertes (seuils par défaut, modifiables par l'admin)
| Alerte | Condition | Niveau |
|---|---|---|
| Aucune impression | 0 impression 24 h après le démarrage (par régie) | Bloquant |
| Rythme | Livré < 80 % du prévu à date (campagne, régie), plan lié requis, après 2 jours | À vérifier |
| Budget mi-campagne | À partir de 50 % de la durée, budget consommé estimé hors ±20 % de l'attendu | À vérifier |
| Écart régie / ad server | Chiffres déclarés par la régie vs ad server, même période, écart > 10 % | À vérifier |
| Emplacement à l'arrêt | Diffusait, puis 0 depuis 2 jours, ou en pause dans l'ad server | Bloquant |

## Fonctionnement
- Campagnes connectées par API : vérifiées par le Worker toutes les 6 h ; démo : par la page.
- Une alerte disparue se ferme ; revenue, elle est de nouveau notifiée.
- E-mail (Resend) aux seuls comptes de l'agence ; sans configuration : cloche seulement.

## À trancher
- **D6** : valeurs des seuils par défaut.
- **D7** : fournisseur d'e-mail ; résumé quotidien unique plutôt qu'un e-mail par alerte.
- Lecture automatique des chiffres des régies (reports reçus par e-mail).
