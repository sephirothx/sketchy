# The one image the deployment runs (#405): the built frontend, the backend and
# its pinned dependencies, and the PostgreSQL client the pre-migration snapshot
# needs. The same image is the web process and the one-shot migration
# (ops/compose/compose.yaml); only the command differs.
#
#   docker build --build-arg SKETCHY_COMMIT_SHA="$(git rev-parse --short HEAD)" -t sketchy .
#
# Building, signing and publishing it by digest is #457's; this file is what
# that pipeline builds.

# --- frontend ---------------------------------------------------------------
FROM node:22.23.4-trixie-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY frontend/ ./
# The build reads the bundled prompt lists, for the official lists' pages
# and the sitemap (scripts/seo-pages.mjs), from where they sit in the tree.
COPY backend/data/ /src/backend/data/
# The build stamps the commit it was made from (vite.config.ts). There is no
# .git in the build context, so the caller says which commit it is.
ARG SKETCHY_COMMIT_SHA=unknown
ARG SKETCHY_COMMIT_DATE=unknown
ENV SKETCHY_COMMIT_SHA=$SKETCHY_COMMIT_SHA SKETCHY_COMMIT_DATE=$SKETCHY_COMMIT_DATE
RUN npm run build

# --- runtime ----------------------------------------------------------------
FROM python:3.14.10-slim-trixie AS runtime

# pg_dump and psql for ops/postgres/migrate-with-snapshot.sh. A dump needs a
# client of the server's major version or newer, and trixie's is 17, the
# version the db service runs and the app requires (#1367, README → Database
# & Configuration). A server upgrade to 18 moves this base image too.
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-17 \
    && rm -rf /var/lib/apt/lists/*

# The paths the repository's own scripts expect: backend/.venv, and
# frontend/dist beside backend/ (app/main.py serves it from there).
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN python -m venv .venv \
    && .venv/bin/pip install --no-cache-dir --no-compile -r requirements.txt
COPY backend/alembic.ini ./
COPY backend/alembic/ alembic/
COPY backend/data/ data/
COPY backend/app/ app/
COPY ops/postgres/migrate-with-snapshot.sh /app/ops/postgres/migrate-with-snapshot.sh
COPY --from=frontend /src/frontend/dist /app/frontend/dist
# Compiled once here, because the container's root filesystem is read-only
# at run time and Python would otherwise recompile on every start.
RUN .venv/bin/python -m compileall -q app alembic .venv

# Not root, and owning nothing it runs: the code and the venv stay root's, so
# a compromised process cannot rewrite what it serves. The one place it
# writes (the snapshot directory) is a mount the operator gives this uid.
RUN useradd --system --uid 10001 --user-group --home-dir /nonexistent --no-create-home sketchy
USER 10001:10001

ENV PATH=/app/backend/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000
EXPOSE 8000

# Readiness, not liveness: it tests the database and the background loops,
# and answers 503 while a drain is under way (README → Reconnection &
# disconnection). Exempt from the HTTPS redirect, so plain HTTP works here.
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=4 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/ready', timeout=4).status == 200 else 1)"]

CMD ["python", "-m", "app.server"]
