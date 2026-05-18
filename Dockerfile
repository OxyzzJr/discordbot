FROM python:3.11-slim

WORKDIR /app

# Dépendances système minimales
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copier et installer les dépendances Python
COPY DiscordCompanion/pyproject.toml .
RUN pip install --no-cache-dir \
    "discord-py>=2.5.2" \
    "flask>=3.1.1" \
    "python-dotenv>=1.1.0"

# Copier le code source
COPY DiscordCompanion/ .

# Dossier pour la base de données persistante
RUN mkdir -p /data
ENV DATABASE_PATH=/data/moderation.db

EXPOSE 5000

CMD ["python", "main.py"]
