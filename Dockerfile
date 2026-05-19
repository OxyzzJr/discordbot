FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY DiscordCompanion/pyproject.toml .
RUN pip install --no-cache-dir \
    "discord-py>=2.5.2" \
    "flask>=3.1.1" \
    "python-dotenv>=1.1.0"

COPY DiscordCompanion/ .

RUN mkdir -p /data
ENV DATABASE_PATH=/data/moderation.db

EXPOSE 5000

CMD ["python", "main.py"]
