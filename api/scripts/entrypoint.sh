#!/usr/bin/env sh
set -e

# Run migrations or stamp head for existing DB created via create_all
python -m api.scripts.ensure_migrations

# If no command passed - start uvicorn by default
if [ "$#" -eq 0 ]; then
  exec uvicorn api.main:app --host 0.0.0.0 --port 8000
fi

exec "$@"
