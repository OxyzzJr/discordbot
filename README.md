# Bot Discord de modération

Bot de modération Discord existant en **deux implémentations interchangeables** qui partagent
le même schéma de base de données, les mêmes variables d'environnement et les mêmes commandes
slash :

| | Python | Rust |
| --- | --- | --- |
| Dossier | `DiscordCompanion/` | `rust-bot/` |
| Stack | [discord.py](https://discordpy.readthedocs.io/) 2.5, Flask, waitress | [serenity](https://github.com/serenity-rs/serenity) 0.12 + [poise](https://github.com/serenity-rs/poise) 0.6, tokio, sqlx, axum |
| Compose | `docker-compose.python.yml` | `docker-compose.rust.yml` |
| Port keep-alive (hôte) | `5000` | `5001` |
| Image Docker | 494 Mo | **154 Mo** |

Les deux versions lisent et écrivent le **même fichier SQLite** : on peut passer de l'une à
l'autre sans perdre les avertissements, les cases ni la configuration des serveurs.

## Sommaire

- [Choisir une version](#choisir-une-version)
- [Démarrage rapide (Docker)](#démarrage-rapide-docker)
- [Configuration](#configuration)
- [Installation manuelle](#installation-manuelle)
- [Commandes](#commandes)
- [Auto-modération](#auto-modération)
- [Basculer d'une version à l'autre](#basculer-dune-version-à-lautre)
- [Structure du projet](#structure-du-projet)
- [Base de données](#base-de-données)
- [Permissions Discord requises](#permissions-discord-requises)

## Choisir une version

Les deux bots couvrent les mêmes 23 commandes slash de modération et les mêmes ~20 listeners
de logs d'audit. Les différences réelles :

| Comportement | Python | Rust |
| --- | --- | --- |
| Auto-modération (spam, majuscules, mentions, blacklist, points de violation) | code présent mais **non chargé** par `main.py` | **actif** |
| Commandes du prototype `/ntm`, `/fdpduserv`, `/turc` | absentes | présentes |
| Boutons de vérification des nouveaux membres après un redémarrage | inertes (l'état vivait en mémoire) | fonctionnels (l'ID du membre est encodé dans le `custom_id`) |
| Port du keep-alive | figé à `5000` | configurable (`KEEPALIVE_PORT`) |
| Recherche d'un banni pour `/unban` | parcourt jusqu'à 2 000 bans | une requête directe |
| Attribution des numéros de case | deux requêtes successives | transaction (pas de doublon possible) |

En clair : la version Rust est un sur-ensemble fonctionnel. La version Python reste dans le
dépôt comme référence et comme filet de repli.

## Démarrage rapide (Docker)

```bash
cp .env.exemple .env      # puis renseigne DISCORD_TOKEN
```

**Version Python :**

```bash
docker compose -f docker-compose.python.yml up -d --build
docker compose -f docker-compose.python.yml logs -f
```

**Version Rust :**

```bash
docker compose -f docker-compose.rust.yml up -d --build
docker compose -f docker-compose.rust.yml logs -f
```

> ⚠️ **Ne lance pas les deux en même temps avec le même `DISCORD_TOKEN`.** Discord accepterait
> les deux sessions et chaque commande slash recevrait deux réponses (dont une en erreur).
> Les deux compose peuvent coexister sur la machine — c'est le token qui doit être unique.

Chaque pile a son propre projet Compose, son conteneur, son volume et son port hôte :

| | Projet Compose | Conteneur | Volume | Port |
| --- | --- | --- | --- | --- |
| Python | `discordbot` | `discord-bot` | `discordbot_bot_data` | `5000` |
| Rust | `discordbot-rust` | `discord-bot-rust` | `discordbot-rust_bot_data` | `5001` |

Le volume est monté sur `/data` et les deux compose forcent
`DATABASE_PATH=/data/moderation.db` : la base survit aux reconstructions d'image.

Routes du keep-alive (identiques dans les deux versions) :

| Route | Réponse |
| --- | --- |
| `/` | Message texte de statut |
| `/status` | JSON : `statut`, `timestamp`, `uptime_secondes` |
| `/health` | JSON : `{"sain": true, "service": "discord-bot"}` |

## Configuration

Un seul `.env` à la racine sert aux deux versions.

| Variable | Requis | Défaut | Utilisée par | Description |
| --- | --- | --- | --- | --- |
| `DISCORD_TOKEN` | ✅ | — | les deux | Token du bot ([portail développeur](https://discord.com/developers/applications)) |
| `OWNER_ID` | — | `0` | les deux | ID Discord autorisé à lancer `!ascend` |
| `MAX_WARNINGS` | — | `3` | les deux | Avertissements avant auto-mute |
| `MUTE_ROLE_NAME` | — | `Muted` | les deux | Nom du rôle de mute (créé s'il n'existe pas) |
| `LOG_CHANNEL_NAME` | — | `mod-logs` | les deux | Nom de salon de logs par défaut |
| `SPAM_THRESHOLD` | — | `5` | les deux | Messages avant détection de spam |
| `SPAM_INTERVAL` | — | `10` | les deux | Fenêtre de détection (secondes) |
| `MAX_MENTIONS` | — | `5` | les deux | Mentions maximum par message |
| `DATABASE_PATH` | — | `moderation.db` | les deux | Chemin du fichier SQLite |
| `KEEPALIVE_PORT` | — | `5000` | Rust | Port d'écoute du serveur HTTP |
| `RUST_LOG` | — | `info,serenity=warn` | Rust | Niveau de log ([syntaxe `tracing`](https://docs.rs/tracing-subscriber/latest/tracing_subscriber/filter/struct.EnvFilter.html)) |

`SPAM_THRESHOLD`, `SPAM_INTERVAL` et `MAX_MENTIONS` ne servent que de valeurs de repli : dès
qu'une ligne existe dans la table `automod_config` pour un serveur, c'est elle qui prime.

### Intents privilégiés

Sur le portail développeur Discord (**ton application → Bot → Privileged Gateway Intents**),
active obligatoirement :

- **SERVER MEMBERS INTENT**
- **MESSAGE CONTENT INTENT**

Sans ça, le bot ne peut pas démarrer.

## Installation manuelle

### Python

Prérequis : Python 3.11 ou plus.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows : .venv\Scripts\activate
pip install -r requirements.txt

cd DiscordCompanion
python main.py
```

### Rust

Prérequis : Rust stable (1.80 ou plus).

```bash
cd rust-bot
cargo run --release
```

Au premier lancement, les deux versions créent la base, appliquent les migrations de schéma et
synchronisent les commandes slash. Une synchronisation globale peut mettre jusqu'à une heure à
se propager sur tous les serveurs.

## Commandes

Toutes les commandes ci-dessous sont des **commandes slash** (`/`), sauf `!ascend`.
`/modhelp` affiche la liste directement dans Discord.

### Sanctions

| Commande | Permission | Description |
| --- | --- | --- |
| `/kick <membre> [raison]` | Expulser des membres | Expulse un membre (confirmation par boutons) |
| `/ban <membre> [raison] [supprimer_jours]` | Bannir des membres | Bannit un membre (confirmation par boutons) |
| `/tempban <membre> <durée> [raison]` | Bannir des membres | Bannissement temporaire, levé automatiquement |
| `/unban <user_id> [raison]` | Bannir des membres | Débannit un utilisateur par son ID |
| `/mute <membre> [durée] [raison]` | Gérer les messages | Attribue le rôle de mute, temporaire si une durée est donnée |
| `/unmute <membre> [raison]` | Gérer les messages | Retire le rôle de mute |

Formats de durée acceptés : `30s`, `10m`, `2h`, `1d`.

Les actions destructives passent par un embed de confirmation éphémère (30 s) et le membre
sanctionné reçoit un DM quand ses messages privés sont ouverts.

### Avertissements

| Commande | Permission | Description |
| --- | --- | --- |
| `/warn <membre> [raison]` | Gérer les messages | Avertit un membre, auto-mute au seuil `MAX_WARNINGS` |
| `/warnings <membre>` | — | Liste paginée des avertissements |
| `/clearwarnings <membre>` | Gérer les messages | Efface tous ses avertissements |

### Cases et historique

| Commande | Permission | Description |
| --- | --- | --- |
| `/case <numéro>` | Gérer les messages | Détail d'un case de modération |
| `/editcase <numéro> <nouvelle_raison>` | Gérer les messages | Corrige la raison d'un case |
| `/historique <membre>` | Gérer les messages | Historique paginé des sanctions |

Chaque sanction reçoit un numéro de case incrémental **par serveur**, rappelé dans le pied de
l'embed de confirmation.

### Messages et salons

| Commande | Permission | Description |
| --- | --- | --- |
| `/purge <nombre> [membre]` | Gérer les messages | Supprime jusqu'à 100 messages, filtrables par auteur |
| `/slowmode [secondes] [salon]` | Gérer les salons | Active le mode lent (`0` pour désactiver) |

### Informations

| Commande | Description |
| --- | --- |
| `/userinfo [membre]` | Profil détaillé (dates, rôles, boost, nombre de sanctions) |
| `/serverinfo` | Statistiques du serveur |
| `/regles` | Affiche les règles configurées |
| `/modhelp` | Liste toutes les commandes de modération |

### Configuration (administrateur)

| Commande | Description |
| --- | --- |
| `/setmodchannel <salon>` | Salon recevant les logs d'audit et les vérifications de nouveaux membres |
| `/setlogchannel <salon>` | Alias historique de `/setmodchannel` (écrit le même réglage) |
| `/setregles <texte>` | Définit les règles du serveur (markdown supporté) |
| `/setwelcome <salon> [message]` | Message de bienvenue — variables `{mention}`, `{server}`, `{count}` |
| `/autorole_create_soumises` | Crée le rôle `soumises` utilisé par la vérification |

### Divertissement *(version Rust uniquement)*

`/ntm`, `/fdpduserv`, `/turc` — reprises du prototype `attached_assets/`.

### Commande owner

`!ascend` est une commande **préfixée** et cachée, réservée à l'utilisateur dont l'ID
correspond à `OWNER_ID`. Elle attribue au propriétaire le rôle assignable le plus haut du
serveur en lui donnant les permissions administrateur. Le message d'invocation est supprimé,
toute réponse part en DM, et la commande n'apparaît pas dans `/modhelp`. Pour un ID non
autorisé, elle ne répond rien du tout.

## Auto-modération

Active dans la version Rust uniquement. Sept filtres tournent sur chaque message (et sur
chaque édition qui change le contenu) ; les membres disposant de « Gérer les messages » en sont
exemptés.

| Filtre | Points |
| --- | --- |
| Spam de messages (fréquence) | 2 |
| Messages répétés identiques (> 10 caractères) | 2 |
| Spam de mentions | 3 |
| Lien d'invitation Discord | 1 |
| Contenu suspect (`free nitro`, `scam`…) | 3 |
| Mot de la blacklist du serveur | 2 |
| Abus de majuscules | 1 |
| Flood de pièces jointes | 2 |

Les points s'accumulent par membre et par serveur, et **expirent au bout de 24 h**. Les paliers
déclenchent automatiquement une sanction, puis remettent le compteur à zéro :

| Total | Action |
| --- | --- |
| 5 | Avertissement enregistré |
| 10 | Mute temporaire (10 min) |
| 15 | Expulsion |
| 20 | Bannissement temporaire (1 h) |

Tous ces seuils sont modifiables par serveur dans la table `automod_config`.

Pour activer l'auto-modération côté Python, ajoute
`await self.load_extension('cogs.automod')` dans `setup_hook()` de `DiscordCompanion/main.py`.

## Basculer d'une version à l'autre

Les deux piles utilisent des volumes distincts. Pour reprendre les données de la version
Python dans la version Rust :

```bash
# 1. Arrêter le bot Python
docker compose -f docker-compose.python.yml down

# 2. Copier la base d'un volume à l'autre
docker volume create discordbot-rust_bot_data
docker run --rm \
  -v discordbot_bot_data:/from:ro \
  -v discordbot-rust_bot_data:/to \
  alpine cp /from/moderation.db /to/moderation.db

# 3. Démarrer le bot Rust
docker compose -f docker-compose.rust.yml up -d --build
```

Dans l'autre sens, il suffit d'inverser les deux volumes. Le schéma étant identique, aucune
conversion n'est nécessaire — la version Rust applique au besoin les `ALTER TABLE` manquants
sur une base ancienne.

Pour revenir en arrière : `docker compose -f docker-compose.rust.yml down` puis
`docker compose -f docker-compose.python.yml up -d`.

## Structure du projet

```
.
├── docker-compose.python.yml   # Pile Python  (port 5000)
├── docker-compose.rust.yml     # Pile Rust    (port 5001)
├── Dockerfile                  # Image Python 3.11-slim
├── requirements.txt            # Dépendances Python
├── .env.exemple                # Modèle de configuration, commun aux deux
│
├── DiscordCompanion/           # ── Implémentation Python ──
│   ├── main.py                 # Intents, chargement des cogs, sync, reconnexion
│   ├── config.py               # Variables d'environnement et couleurs d'embeds
│   ├── cogs/
│   │   ├── moderation.py       # Sanctions, cases, purge, infos, configuration
│   │   ├── logging.py          # Logs d'audit
│   │   ├── autorole.py         # Vérification des arrivées + rôle « soumises »
│   │   ├── owner.py            # Commande owner cachée
│   │   └── automod.py          # Auto-modération — présent mais NON chargé
│   └── utils/
│       ├── database.py         # Schéma SQLite, requêtes, durées
│       ├── keepalive.py        # Flask + waitress, port 5000
│       ├── permissions.py      # Vérifications de permissions
│       └── ui.py               # Vues : pagination et confirmation
│
└── rust-bot/                   # ── Implémentation Rust ──
    ├── Dockerfile              # Build multi-étapes → image debian-slim
    ├── Cargo.toml
    └── src/
        ├── main.rs             # Client, intents, framework, reconnexion
        ├── config.rs           # Variables d'environnement + palette
        ├── data.rs             # État partagé (pool, trackers, caches)
        ├── db.rs               # Schéma SQLite + toutes les requêtes
        ├── helpers.rs          # Rôle Muted, hiérarchie, audit log, vues
        ├── util.rs             # Durées, dates, troncature
        ├── keepalive.rs        # Serveur axum
        ├── commands/           # moderation, info, settings, owner, fun
        └── events/             # logging, automod, autorole, tasks
```

Le fichier `package.json` est un reliquat d'une ancienne version Node et n'est pas utilisé.
`DiscordCompanion/attached_assets/` contient un prototype antérieur, conservé pour mémoire.

## Base de données

SQLite unique, créée et migrée automatiquement au démarrage par l'une ou l'autre version. Les
migrations passent par des `ALTER TABLE` tolérants, ce qui permet de faire évoluer une base
existante sans la recréer.

| Table | Contenu |
| --- | --- |
| `warnings` | Avertissements par membre et par serveur |
| `mutes` | Mutes actifs, avec date d'expiration pour les mutes temporaires |
| `tempbans` | Bannissements temporaires et date de débannissement |
| `sanctions` | Historique complet, source des numéros de case |
| `guild_settings` | Salon modérateur, rôle de mute, règles, message de bienvenue |
| `word_blacklist` | Mots interdits (auto-modération) |
| `violation_points` | Points de violation par membre (auto-modération) |
| `automod_config` | Seuils et paliers de sanction (auto-modération) |

Une tâche périodique tourne toutes les minutes dans les deux versions pour lever les tempbans
et les mutes temporaires arrivés à échéance, y compris après un redémarrage du bot.

## Permissions Discord requises

- Gérer les rôles — *le rôle du bot doit être placé **au-dessus** des rôles qu'il attribue*
- Expulser des membres
- Bannir des membres
- Gérer les messages
- Gérer les salons *(mode lent)*
- Voir les logs d'audit *(pour attribuer les actions dans les logs)*
- Lire et envoyer des messages, intégrer des liens

En cas d'erreur de hiérarchie sur un mute ou l'attribution d'un rôle, vérifie d'abord la
position du rôle du bot dans la liste des rôles du serveur.
