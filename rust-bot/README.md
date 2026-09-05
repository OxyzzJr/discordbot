# discord-mod-bot — implémentation Rust

Portage Rust du bot de modération. **La documentation d'usage (commandes, configuration,
Docker, migration des données) se trouve dans le [README à la racine](../README.md).**
Ce fichier ne couvre que le développement.

## Stack

| Rôle | Crate |
| --- | --- |
| Client Discord | `serenity` 0.12 |
| Framework de commandes | `poise` 0.6 |
| Runtime async | `tokio` (macros + rt-multi-thread) |
| Base de données | `sqlx` 0.9 (SQLite, async) |
| Environnement | `dotenvy` |
| Erreurs / logs | `anyhow`, `tracing` |
| Keep-alive HTTP | `axum` |
| État partagé | `dashmap` |

## Développement

```bash
cp .env.exemple .env      # puis renseigne DISCORD_TOKEN

cargo check               # itération rapide
cargo run                 # build debug
cargo run --release       # build optimisé (LTO, codegen-units=1)
```

Le profil `release` active `lto = true` et `codegen-units = 1` : compter ~3 min de compilation
complète, contre ~40 s en debug.

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

## Points d'implémentation

- **État partagé** — `Data` regroupe le pool SQLite, la config et cinq `DashMap` (fenêtres de
  spam, dernier message par membre, flood de fichiers, cache de blacklist, instantanés
  emojis/stickers). `DashMap` évite de sérialiser tous les listeners derrière un `RwLock`
  unique.
- **Cache de messages** — le client est configuré avec `max_messages = 1000` : sans lui,
  `MessageDelete` ne transmet qu'un identifiant et le log de suppression serait vide.
- **Raisons d'audit** — `Member::add_role` / `remove_role` et `GuildId::unban` ne transmettent
  pas de raison en serenity 0.12. Les wrappers de `helpers.rs` passent par `Http` directement
  pour conserver les entrées d'audit.
- **Emojis / stickers** — la gateway ne transmet que l'état courant, jamais le précédent. Un
  instantané par serveur est maintenu dans `Data` pour calculer le diff ; aucun log n'est émis
  au premier événement suivant un démarrage.
- **Vues interactives** — `ConfirmView` et `PaginationView` sont reconstruits avec
  `ComponentInteractionCollector` (timeouts 30 s et 120 s). Les boutons de vérification des
  nouveaux membres, eux, encodent l'ID du membre dans leur `custom_id` et restent donc
  fonctionnels après un redémarrage.

## Base de données

Le schéma est identique à celui de la version Python : la base `moderation.db` existante est
reprise telle quelle, migrations `ALTER TABLE` incluses. Les deux bots ne doivent pas tourner
en même temps sur la même base.
