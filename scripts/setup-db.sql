-- One-time database setup.
--
-- Run as a superuser:
--
--   psql -U postgres -f scripts/setup-db.sql
--
-- The password is requested interactively rather than written here, so it never
-- reaches this file, git history, or your shell history. This file is committed;
-- a password typed into it would be committed too, and git history is painful to
-- clean afterwards.
--
-- Afterwards, put the matching URL in .env (which is gitignored):
--
--   UPA_DATABASE_URL=postgresql+asyncpg://upa:the-password@localhost:5432/upa_dev

\prompt 'Password for role upa: ' upa_password

-- CREATEDB is required: the test suite creates a uniquely named throwaway
-- database for each run and drops it afterwards, so test runs never touch
-- upa_dev.
CREATE ROLE upa WITH LOGIN PASSWORD :'upa_password' CREATEDB;

CREATE DATABASE upa_dev OWNER upa;
