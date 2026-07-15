FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY datasette.yaml ./
COPY deploy/entrypoint.sh ./entrypoint.sh
# Seed databases: installed onto the volume ONLY if not already present,
# so deploys never overwrite live contributor data.
COPY census.db assignments.db internal.db ./seed/
RUN chmod +x entrypoint.sh

EXPOSE 8080
CMD ["./entrypoint.sh"]
