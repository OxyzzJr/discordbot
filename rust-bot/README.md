# discord-mod-bot

Portage Rust du bot de modération `DiscordCompanion` (Python / discord.py).

## Stack

| Rôle | Crate |
|---|---|
| Client Discord | `serenity` 0.12 |
| Framework de commandes | `poise` 0.6 |
| Runtime async | `tokio` (macros + rt-multi-thread) |
| Base de données | `sqlx` 0.9 (SQLite, async) |
| Environnement | `dotenvy` |
| Erreurs / logs | `anyhow`, `tracing` |
| Keep-alive HTTP | `axum` |

## Arborescence

```
src/
├── main.rs              init client, intents, framework, boucle de reconnexion
├── config.rs            variables d'environnement + palette d'embeds
├── data.rs              état partagé (Data : pool, trackers, caches)
├── db.rs                schéma SQLite + toutes les requêtes
├── helpers.rs           rôle Muted, hiérarchie, audit log, ConfirmView, PaginationView
├── util.rs              durées, dates, troncature
├── keepalive.rs         serveur HTTP /, /status, /health
├── commands/
│   ├── moderation.rs    kick ban tempban unban mute unmute warn warnings
│   │                    clearwarnings purge slowmode
│   ├── info.rs          userinfo serverinfo historique case editcase regles modhelp
│   ├── settings.rs      setregles setwelcome setmodchannel setlogchannel
│   │                    autorole_create_soumises
│   ├── owner.rs         !ascend (préfixée, cachée)
│   └── fun.rs           ntm fdpduserv turc
└── events/
    ├── mod.rs           dispatcher FullEvent
    ├── logging.rs       ~20 listeners d'audit
    ├── automod.rs       7 filtres + escalade par points
    ├── autorole.rs      vérification des nouveaux membres (boutons)
    └── tasks.rs         boucle 1 min : tempbans et mutes expirés
```

## Démarrage

```bash
cp .env.exemple .env      # puis renseigner DISCORD_TOKEN
cargo run --release
```

## Base de données

Le schéma est identique à celui de la version Python : la base `moderation.db`
existante est reprise telle quelle, migrations `ALTER TABLE` incluses. Les deux
bots ne doivent pas tourner en même temps sur la même base.
