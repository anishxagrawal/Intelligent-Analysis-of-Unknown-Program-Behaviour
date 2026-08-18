-- One-time database setup.
--
-- Run as a superuser, choosing your own password:
--
--   psql -U postgres -f scripts/setup-db.sql
--
-- Then put the matching URL in .env:
--
--   UPA_DATABASE_URL=postgresql+asyncpg://upa:your-password@localhost:5432/upa_dev

-- CREATEDB is required: the test suite creates a uniquely named throwaway
-- database for each run and drops it afterwards, so test runs never touch
-- upa_dev.
CREATE ROLE upa WITH LOGIN PASSWORD 'change-me' CREATEDB;

CREATE DATABASE upa_dev OWNER upa;
