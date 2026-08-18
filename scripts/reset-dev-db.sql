-- Reset the development database schema.
--
--   psql -U upa -d upa_dev -f scripts/reset-dev-db.sql
--
-- WHY THIS EXISTS
--
-- Until v3 introduces Alembic, tables are created at startup with
-- SQLAlchemy's create_all. That only creates tables which do not yet exist -
-- it never alters an existing one. So whenever a model changes shape, an
-- existing development database keeps the old columns and inserts start
-- failing with "column ... does not exist".
--
-- Tests are unaffected: each run builds a throwaway database from scratch.
--
-- THIS DESTROYS ALL DEVELOPMENT DATA. That is fine for a development database
-- holding sample submissions, and is exactly what you do not want to run
-- anywhere else. From v3, migrations replace this entirely.

DROP TABLE IF EXISTS jobs;
DROP TABLE IF EXISTS samples;
