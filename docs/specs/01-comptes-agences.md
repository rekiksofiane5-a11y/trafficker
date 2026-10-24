# 01 — Comptes et agences

## Objectif
Chaque agence travaille dans un espace isolé ; Agopis (super-admin) peut gérer plusieurs agences.

## Rôles
| Rôle | Droits |
|---|---|
| Utilisateur | Ses tâches et celles de son agence ; ajoute ses corrections, demandes, surveillances ; supprime les siennes |
| Admin d'agence | + comptes de **son** agence, réglages de l'agence (règles client, annonceurs, templates, seuils), réponses aux demandes, diagnostic ad servers |
| Super-admin Agopis | + toutes les agences (e-mail listé dans le secret `SUPERADMIN_EMAILS`) |

## Parcours
1. Premier lancement : création du premier admin avec la clé d'installation (secret `TRAFFICKER_PASSWORD`).
2. Connexion e-mail + mot de passe (10 caractères min.) ; session 12 h ; 5 échecs en 5 min bloquent l'IP.
3. Administration (admin) : ajouter / supprimer des comptes ; l'agence est imposée sauf pour le super-admin.
4. Paramètres : changer son mot de passe.

## Règles
- Une tâche appartient à une agence ; visible par les membres de l'agence, modifiable par eux, supprimable par l'auteur ou un admin.
- Listes partagées (demandes, corrections, surveillances) : auteur imposé par le serveur.
- Mots de passe : PBKDF2-SHA256, itérations par compte, relevées à la connexion (secret `PBKDF2_ITERATIONS`).

## À trancher
- SSO (Google Workspace / Microsoft) ou Cloudflare Access pour les agences.
- Réinitialisation de mot de passe par e-mail (aujourd'hui : l'admin recrée le compte).
- Journal des actions sensibles (création / suppression de comptes, changements de règles).
