-- One-time setup a superuser runs in the Sketchy database after initdb (#889).
-- Idempotent: safe to run again after an upgrade or on an existing cluster.
--
--   psql -v ON_ERROR_STOP=1 -d sketchy -f ops/postgres/init.sql
--
-- Passwords are set separately (\password sketchy_owner, sketchy_app,
-- sketchy_monitor), so no secret is tracked here.

-- Statement statistics. The library is preloaded by sketchy.conf; the view
-- lives in this database. Not a trusted extension, so the application's
-- migrations cannot create it themselves.
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- What postgres_exporter connects as: pg_monitor reads every statistics view
-- and pg_stat_statements for all users, and nothing else - no table data.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sketchy_monitor') THEN
        CREATE ROLE sketchy_monitor LOGIN;
    END IF;
END
$$;
GRANT pg_monitor TO sketchy_monitor;
ALTER ROLE sketchy_monitor SET application_name = 'sketchy-monitor';
-- A scrape that hangs is worse than one that fails: the exporter reports the
-- failure, and a hung query holds a connection out of a small budget.
ALTER ROLE sketchy_monitor SET statement_timeout = '10s';
ALTER ROLE sketchy_monitor SET lock_timeout = '1s';

-- Three roles, not one (#896). The process that answers anonymous traffic
-- must not be able to drop, truncate or alter what it serves, nor rewrite
-- the two ledgers moderation and scoring disputes rest on.
--
--   sketchy_owner   owns the schema and every table; used only by
--                   `python -m app.db.migrate` (MIGRATION_DATABASE_URL)
--   sketchy_app     the web process and operator commands (DATABASE_URL):
--                   rows only. Its grants are applied by the migration
--                   command after every upgrade (backend/app/db/roles.py),
--                   so a new table is granted in the transaction that makes it.
--   sketchy_monitor postgres_exporter, above
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sketchy_owner') THEN
        CREATE ROLE sketchy_owner LOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sketchy_app') THEN
        CREATE ROLE sketchy_app LOGIN;
    END IF;
END
$$;

-- The owner creates every table, so it owns the schema they live in; nobody
-- else may create anything there.
ALTER SCHEMA public OWNER TO sketchy_owner;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- Only the three roles may connect; the application may make temporary
-- tables, which it does not use today and a driver may.
DO $$
BEGIN
    EXECUTE format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database());
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO sketchy_owner, sketchy_monitor', current_database());
    EXECUTE format('GRANT CONNECT, TEMPORARY ON DATABASE %I TO sketchy_app', current_database());
END
$$;
