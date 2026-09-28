-- ============================================================
-- PostgreSQL 18 + pgAdmin setup (offline PC — no Docker)
-- ============================================================
-- Step A: connect Query Tool to database "postgres" (superuser).
-- Step B: run the ROLE block below.
-- Step C: in pgAdmin UI create database "route_card" owned by route_card
--         OR run:  CREATE DATABASE route_card OWNER route_card;
-- Step D: reconnect Query Tool to database "route_card" and run
--         setup_pgadmin_grants.sql
-- ============================================================

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'route_card') THEN
    CREATE ROLE route_card LOGIN PASSWORD 'route_card';
  ELSE
    ALTER ROLE route_card WITH LOGIN PASSWORD 'route_card';
  END IF;
END
$$;

-- After the role exists, create the DB once (ignore error if it already exists):
-- CREATE DATABASE route_card OWNER route_card;
