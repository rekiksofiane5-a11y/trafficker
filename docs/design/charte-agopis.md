# Charte Agopis et revue de design — 24/10/2026

Le projet s'appelle désormais **Agopis** (anciennement Umnia). La charte vient du premier jet de site vitrine et s'applique au site comme à l'application.

- **Système de design** (référence vivante, à jour avec ce dépôt) : https://claude.ai/artifact/WQn6AoVs5QDR3UaQgpeupw — jetons (nuit / clair), Inter, espacements, rayons, ombres, logo, composants Button, NavPill, Headline, StatusChip, Card.
- **Site vitrine** : `site/` (servi à la racine `/`). **Application** : `web/index.html` (servie sous `/app/`). Bouton « Se connecter » du site → `/app/` ; logo de l'app → site.
- **Thème** : sombre par défaut, clair au choix ; choix mémorisé (`agopis_theme`) et partagé entre site et app.

## Correspondance des jetons
| Jeton | Nuit | Clair | Variable vitrine | Variable app |
|---|---|---|---|---|
| bg | #0c1128 | #f4f5fb | `--bg` | `--bg` |
| surface | #151c3a | #fdfdff | `--surface` | `--card` |
| ink / ink-muted | #f2f4fb / #aab3c7 | #131b37 / #4c5873 | `--text` / `--body` | `--text` / `--muted` |
| neon | #00f0ff | #006ab9 | `--neon` | `--neon`, `--gold` |
| violet | #b026ff | #7740c5 | `--purple` | `--purple` |
| cta / cta-ink | #fff / #10152d | #131b37 / #fff | `.pill-button` | `--accent` / `--accent-text` |

## Audit d'accessibilité (WCAG 2.1 AA)
Méthode : axe-core 4.10 (règles wcag2a/aa, wcag21a/aa) sur le site et l'app (accueil, check de mise en ligne), thèmes nuit et clair ; parcours au clavier ; cibles tactiles à 390 px ; débordement à 390 et 720 px (≈ zoom 200 %).

| # | Constat | Critère | Gravité | Correction |
|---|---|---|---|---|
| 1 | Poignées de largeur de colonne (séparateurs focusables) sans `aria-valuenow` | 4.1.2 | Critique | Valeur, min et max annoncés, mis à jour au redimensionnement |
| 2 | Site, thème clair : texte secondaire #66728a à 4,1–4,4:1 | 1.4.3 | Majeur | #5b6780 (≥ 4,8:1) |
| 3 | App, thème clair : vert « réussi » #087a71 à 4,42:1 sur les puces | 1.4.3 | Majeur | #066d66 (5,26:1) |
| 4 | App, thème clair : texte du bouton « Aide » à 3,2:1 sur le dégradé | 1.4.3 | Majeur | Texte blanc en thème clair (≥ 5,6:1) |
| 5 | Mobile : bouton de thème 34 px, « Demander une démo » 34 px, icônes de l'app 40 px | 2.5.5 | Mineur | 44 px minimum sous 760 px |

Contrôles passés : ordre de tabulation logique, lien d'évitement sur le site, anneau de focus 3 px `neon` partout, fenêtres natives (`dialog`) pour les pop-ups, Échap ferme l'historique, l'aide et les menus, illustrations décoratives masquées aux lecteurs d'écran (`aria-hidden`), animations désactivées si « réduire les animations » est demandé (site et trame de l'app), aucun débordement horizontal à 390 et 720 px.

À tester à la main : VoiceOver / NVDA sur l'aperçu CM360 (glisser-déposer : l'alternative clavier est la modification en masse) et sur la cloche.

## Revue de design
- **Ce qui marche** : hiérarchie nette (titre 900 très serré → bouton pilule blanc → illustration) ; la même barre en pilule givrée, les mêmes titres et le même cyan relient le site et l'app ; le dégradé est réservé à un mot par titre.
- **Corrigé** : élisions (« d'Agopis »), phrase qui décrivait la maquette au lieu du produit, accroche de l'app (« Déposez votre plan média, Agopis s'occupe du reste. ») ; cartes de template gardées en carte (pas en pilule) ; titre de tâche en 800.
- **Captures réelles** : la section « Du plan à la diffusion » montre l'app (PM prêt, plan classé et aperçu CM360, points à vérifier, check de mise en ligne) avec des données fictives (« Marque Démo », régies renommées). Images : `site/captures/`, refaites par `python3 tools/captures_vitrine.py` après toute évolution visible de l'interface.
- **Pistes** : texte vertical des cartes repliées de la galerie difficile à lire, à remplacer par un titre court horizontal sur mobile ; icône du logo absente du pied de page.
