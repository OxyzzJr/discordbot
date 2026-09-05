# ── Étape 1 : compilation ────────────────────────────────────────────────────
FROM rust:1-slim-bookworm AS builder

WORKDIR /build

# Les dépendances sont compilées avant le code applicatif : tant que
# Cargo.toml/Cargo.lock ne bougent pas, cette couche reste en cache.
COPY Cargo.toml Cargo.lock ./
RUN mkdir src \
    && echo 'fn main() {}' > src/main.rs \
    && cargo build --release \
    && rm -rf src target/release/deps/discord_mod_bot*

COPY src ./src
RUN cargo build --release

# ── Étape 2 : image finale ───────────────────────────────────────────────────
# SQLite est compilé en statique et le TLS passe par rustls : seul le magasin
# de certificats racine est nécessaire à l'exécution.
FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /build/target/release/discord-mod-bot /usr/local/bin/discord-mod-bot

RUN mkdir -p /data
ENV DATABASE_PATH=/data/moderation.db
ENV RUST_LOG=info,serenity=warn

EXPOSE 5000

CMD ["discord-mod-bot"]
