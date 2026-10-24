# 09 — Assistant d'aide

## Objectif
Guider l'utilisateur dans Umnia (bouton « ✦ Aide »), sans accès aux tâches ni aux données.

## Règles
- Envoyé : la conversation et le nom de l'écran ; e-mails et URL masqués ; rappel de ne pas coller de données client.
- Connaissance : mode d'emploi `web/assistant_guide.js` (à tenir à jour avec ces specs).
- Réponses courtes, boutons cités tels quels, pas d'invention ; hors sujet refusé poliment.
- Modèle Claude Opus 5.5, effort bas, prompt système en cache, repli serveur en cas de refus.
- Clé Umnia (secret `ANTHROPIC_API_KEY`) ; plafond par utilisateur et par jour (`ASSISTANT_DAILY_LIMIT`, 60) ; aucune conversation stockée.

## À trancher
- Évaluation des réponses (👍 / 👎) et suivi des questions mal servies.
- Liens directs vers les écrans cités ; visite guidée au premier lancement.
