-- One-time setup a superuser runs in the Sketchy database after initdb (#889).
-- Idempotent: safe to run again after an upgrade or on an existing cluster.
--
--   psql -v ON_ERROR_STOP=1 -d sketchy -f ops/postgres/init.sql
--
-- The monitor role's password is set separately (\password sketchy_monitor),
-- so no secret is tracked here.

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
