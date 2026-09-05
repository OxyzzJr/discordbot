# Bot Discord de modération

Bot Discord de modération écrit en Python avec [discord.py](https://discordpy.readthedocs.io/).
Il fournit des commandes slash de sanction (kick, ban, tempban, mute, warn), un système de
« cases » persistant en SQLite, des logs d'audit détaillés, une vérification des nouveaux
membres par boutons, et un petit serveur HTTP de keep-alive pour l'hébergement.

## Sommaire

- [Fonctionnalités](#fonctionnalités)
- [Installation](#installation)
- [Configuration](#configuration)
- [Lancement](#lancement)
- [Docker](#docker)
- [Commandes](#commandes)
- [Structure du projet](#structure-du-projet)
- [Base de données](#base-de-données)
- [Permissions Discord requises](#permissions-discord-requises)

## Fonctionnalités

- **Sanctions** — `kick`, `ban`, `tempban`, `unban`, `mute` (temporaire ou permanent), `unmute`.
  Les actions destructives (ban, kick, tempban) passent par un embed de confirmation éphémère
  avec boutons, et le membre sanctionné reçoit un DM quand c'est possible.
- **Avertissements** — `warn` / `warnings` / `clearwarnings`, avec auto-mute déclenché quand le
  seuil `MAX_WARNINGS` est atteint.
- **Système de cases** — chaque sanction reçoit un numéro de case consultable (`/case`) et dont
  la raison peut être corrigée après coup (`/editcase`). Historique complet par membre
  (`/historique`, paginé).
- **Expiration automatique** — une tâche tourne toutes les minutes pour lever les tempbans et
  les mutes temporaires expirés, y compris après un redémarrage du bot.
- **Logs d'audit** — arrivées/départs, bans/unbans, changements de pseudo et de rôles, activité
  vocale (connexion, changement de salon, mute/sourdine, stream), suppressions de messages
  (unitaires et en masse), création/suppression/édition de salons, rôles, invitations, emojis,
  stickers et threads. Le salon cible se configure avec `/setlogchannel`.
- **Vérification des nouveaux membres** — à chaque arrivée, un embed avec boutons ✅/❌ est envoyé
  dans le salon modérateur (`/setmodchannel`) pour attribuer ou non le rôle `soumises`.
- **Configuration par serveur** — règles (`/setregles`, `/regles`) et message de bienvenue
  (`/setwelcome`) stockés en base, indépendants pour chaque guilde.
- **Keep-alive HTTP** — serveur Flask servi par waitress sur le port 5000, avec `/`, `/status`
  et `/health`, pour les hébergeurs qui exigent un port ouvert (Render, Railway, etc.).
- **Reconnexion automatique** — la boucle principale relance le bot après une déconnexion ou une
  erreur inattendue.

## Installation

Prérequis : Python 3.11 ou plus.

```bash
git clone <url-du-dépôt>
cd discordbot

python -m venv .venv
source .venv/bin/activate        # Windows : .venv\Scripts\activate

pip install -r requirements.txt
```

## Configuration

Copie `.env.exemple` vers `.env` à la racine du projet et remplis les valeurs :

```bash
cp .env.exemple .env
```

| Variable | Requis | Défaut | Description |
| --- | --- | --- | --- |
| `DISCORD_TOKEN` | ✅ | — | Token du bot ([portail développeur Discord](https://discord.com/developers/applications)) |
| `OWNER_ID` | — | `0` | ID Discord du propriétaire du bot (commandes owner) |
| `MAX_WARNINGS` | — | `3` | Nombre d'avertissements avant auto-mute |
| `MUTE_ROLE_NAME` | — | `Muted` | Nom du rôle de mute (créé automatiquement s'il n'existe pas) |
| `LOG_CHANNEL_NAME` | — | `mod-logs` | Nom du salon de logs par défaut |
| `SPAM_THRESHOLD` | — | `5` | Messages avant détection de spam |
| `SPAM_INTERVAL` | — | `10` | Fenêtre de détection de spam (secondes) |
| `MAX_MENTIONS` | — | `5` | Mentions maximum par message |
| `DATABASE_PATH` | — | `moderation.db` | Chemin du fichier SQLite |

### Intents privilégiés

Sur le portail développeur Discord (**ton application → Bot → Privileged Gateway Intents**),
active obligatoirement :

- **SERVER MEMBERS INTENT**
- **MESSAGE CONTENT INTENT**

Sans ça, le bot refuse de démarrer et affiche un message d'erreur explicite.

## Lancement

```bash
cd DiscordCompanion
python main.py
```

Au démarrage, le bot initialise la base SQLite, charge les cogs et synchronise les commandes
slash auprès de Discord. La synchronisation globale peut prendre jusqu'à une heure pour être
visible sur tous les serveurs.

Le serveur keep-alive écoute sur `http://localhost:5000` :

| Route | Réponse |
| --- | --- |
| `/` | Message texte de statut |
| `/status` | JSON : statut, timestamp, uptime en secondes |
| `/health` | JSON : `{"sain": true, "service": "discord-bot"}` |

## Docker

```bash
cp .env.exemple .env      # puis remplis DISCORD_TOKEN
docker compose up -d --build
```

Le `docker-compose.yml` monte un volume `bot_data` sur `/data` : la base de données
(`DATABASE_PATH=/data/moderation.db`) survit aux reconstructions du conteneur. Le port 5000 est
exposé pour le keep-alive et le conteneur redémarre automatiquement (`restart: unless-stopped`).

Logs :

```bash
docker compose logs -f bot
```

## Commandes

Toutes les commandes ci-dessous sont des **commandes slash** (`/`). `/modhelp` les affiche
directement dans Discord.

### Sanctions

| Commande | Permission | Description |
| --- | --- | --- |
| `/kick <membre> [raison]` | Expulser des membres | Expulse un membre (avec confirmation) |
| `/ban <membre> [raison] [supprimer_jours]` | Bannir des membres | Bannit un membre (avec confirmation) |
| `/tempban <membre> <durée> [raison]` | Bannir des membres | Bannissement temporaire, levé automatiquement |
| `/unban <user_id> [raison]` | Bannir des membres | Débannit un utilisateur par son ID |
| `/mute <membre> [durée] [raison]` | Gérer les messages | Attribue le rôle de mute, temporaire si une durée est fournie |
| `/unmute <membre> [raison]` | Gérer les messages | Retire le rôle de mute |

Formats de durée acceptés : `30s`, `10m`, `2h`, `1d`.

### Avertissements

| Commande | Permission | Description |
| --- | --- | --- |
| `/warn <membre> [raison]` | Gérer les messages | Avertit un membre, auto-mute au seuil `MAX_WARNINGS` |
| `/warnings <membre>` | Gérer les messages | Liste les avertissements d'un membre |
| `/clearwarnings <membre>` | Gérer les messages | Efface tous ses avertissements |

### Cases et historique

| Commande | Description |
| --- | --- |
| `/case <numéro>` | Affiche le détail d'un case de modération |
| `/editcase <numéro> <nouvelle_raison>` | Corrige la raison d'un case |
| `/historique <membre>` | Historique paginé des sanctions d'un membre |

### Messages et salons

| Commande | Permission | Description |
| --- | --- | --- |
| `/purge <nombre> [membre]` | Gérer les messages | Supprime des messages, filtrables par auteur |
| `/slowmode [secondes] [salon]` | Gérer les salons | Active le mode lent (`0` pour le désactiver) |

### Informations

| Commande | Description |
| --- | --- |
| `/userinfo [membre]` | Profil détaillé d'un membre (dates, boost, sanctions) |
| `/serverinfo` | Statistiques du serveur |
| `/regles` | Affiche les règles configurées |
| `/modhelp` | Liste toutes les commandes de modération |

### Configuration (administrateur)

| Commande | Description |
| --- | --- |
| `/setlogchannel <salon>` | Définit le salon des logs d'audit |
| `/setmodchannel <salon>` | Définit le salon où arrivent les vérifications de nouveaux membres |
| `/setregles <texte>` | Définit les règles du serveur (markdown supporté) |
| `/setwelcome <salon> [message]` | Configure le message de bienvenue — variables `{mention}`, `{server}`, `{count}` |
| `/autorole_create_soumises` | Crée le rôle `soumises` utilisé par la vérification |

### Commande owner

`!ascend` est une commande préfixe cachée, réservée à l'utilisateur dont l'ID correspond à
`OWNER_ID`. Elle attribue au propriétaire le rôle assignable le plus haut du serveur en lui
donnant les permissions administrateur. Le message d'invocation est supprimé et toute réponse
part en DM. Elle n'apparaît volontairement pas dans `/modhelp`.

## Structure du projet

```
.
├── Dockerfile                  # Image Python 3.11-slim
├── docker-compose.yml          # Service + volume persistant pour la base
├── requirements.txt            # Dépendances Python
├── .env.exemple                # Modèle de configuration
└── DiscordCompanion/
    ├── main.py                 # Point d'entrée : intents, cogs, sync, reconnexion
    ├── config.py               # Lecture des variables d'environnement et couleurs d'embeds
    ├── moderation.db           # Base SQLite (créée au premier lancement)
    ├── cogs/
    │   ├── moderation.py       # Sanctions, cases, purge, infos, configuration
    │   ├── logging.py          # Logs d'audit (membres, vocal, messages, salons, rôles…)
    │   ├── autorole.py         # Vérification des arrivées + rôle « soumises »
    │   ├── owner.py            # Commande owner cachée
    │   └── automod.py          # Auto-modération — présent mais NON chargé (voir ci-dessous)
    └── utils/
        ├── database.py         # Schéma SQLite, requêtes, parsing/formatage des durées
        ├── keepalive.py        # Serveur Flask + waitress sur le port 5000
        ├── permissions.py      # Décorateurs de vérification de permissions
        └── ui.py               # Vues Discord : pagination et confirmation
```

> **Note** — `cogs/automod.py` (détection de spam, majuscules, mentions, mots blacklistés,
> système de points de violation) est toujours dans le dépôt mais n'est plus chargé par
> `main.py`. Ses tables SQLite (`word_blacklist`, `violation_points`, `automod_config`) sont
> encore créées à l'initialisation. Pour le réactiver, ajoute
> `await self.load_extension('cogs.automod')` dans `setup_hook()`.

Le fichier `package.json` est un reliquat d'une ancienne version Node du bot et n'est pas utilisé.

## Base de données

SQLite, créée et migrée automatiquement au démarrage (`init_db()`), avec des `ALTER TABLE`
tolérants pour les mises à jour de schéma sur une base existante.

| Table | Contenu |
| --- | --- |
| `warnings` | Avertissements par membre et par serveur |
| `mutes` | Mutes actifs, avec date d'expiration pour les mutes temporaires |
| `tempbans` | Bannissements temporaires et date de débannissement |
| `sanctions` | Historique complet des sanctions, source des numéros de case |
| `guild_settings` | Salon de logs, salon modérateur, rôle de mute, règles, bienvenue |
| `word_blacklist` | Mots interdits (automod) |
| `violation_points` | Points de violation par membre (automod) |
| `automod_config` | Seuils et paliers de sanction (automod) |

## Permissions Discord requises

Le bot a besoin des permissions suivantes sur le serveur :

- Gérer les rôles *(rôle du bot placé **au-dessus** des rôles qu'il doit attribuer)*
- Expulser des membres
- Bannir des membres
- Gérer les messages
- Gérer les salons *(pour le mode lent)*
- Voir les logs d'audit *(pour attribuer les actions dans les logs)*
- Lire et envoyer des messages, intégrer des liens

En cas d'erreur de hiérarchie sur un mute ou l'attribution d'un rôle, vérifie d'abord la position
du rôle du bot dans la liste des rôles du serveur.
