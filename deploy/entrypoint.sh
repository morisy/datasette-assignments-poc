#!/bin/sh
# Seed the volume on first boot only, then start Datasette.
set -e

mkdir -p /data
for f in census.db assignments.db internal.db; do
  if [ ! -f "/data/$f" ]; then
    echo "seeding /data/$f"
    cp "/app/seed/$f" "/data/$f"
  fi
done

exec datasette serve /data/census.db /data/assignments.db \
  --internal /data/internal.db \
  -c /app/datasette.yaml \
  --secret "$DATASETTE_SECRET" \
  --setting sql_time_limit_ms 3000 \
  -h 0.0.0.0 -p 8080
