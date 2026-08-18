-- Reset the development database schema.
--
--   psql -U upa -d upa_dev -f scripts/reset-dev-db.sql
--   alembic upgrade head
--
-- WHY THIS EXISTS
--
-- From v3 the schema is managed by Alembic, and `alembic upgrade head` is the
-- normal way to change it. This script is the escape hatch for the one case
-- migrations cannot fix: a development database left in a state no revision
-- describes, usually because it was built by the create_all startup path that
-- v1 and v2 used, or because a migration was edited after being applied.
--
-- Dropping alembic_version is what makes the next upgrade start from nothing.
-- Without it, Alembic believes the schema is already at head and does nothing.
--
-- Tests never need this: each run builds a throwaway database and migrates it
-- from scratch.
--
-- THIS DESTROYS ALL DEVELOPMENT DATA. That is fine for a development database
-- holding sample submissions, and is exactly what you do not want to run
-- anywhere else.

DROP TABLE IF EXISTS jobs;
DROP TABLE IF EXISTS samples;
DROP TABLE IF EXISTS alembic_version;

DROP TYPE IF EXISTS run_outcome;
DROP TYPE IF EXISTS job_status;
