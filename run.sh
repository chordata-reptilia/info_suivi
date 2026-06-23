#!/usr/bin/env bash
# Wrapper de lancement pour cron : charge le secret (.env) puis lance la veille.
set -euo pipefail
cd "$(dirname "$0")"

# charge les variables de .env si présent (DISCORD_WEBHOOK_URL...)
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi

exec ./.venv/bin/python veille.py
