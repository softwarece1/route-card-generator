-- Run in pgAdmin Query Tool connected to database: route_card
-- (PostgreSQL 18 local install — no Docker)

GRANT ALL ON SCHEMA public TO route_card;

CREATE SCHEMA IF NOT EXISTS route_card AUTHORIZATION route_card;
GRANT ALL ON SCHEMA route_card TO route_card;
ALTER DEFAULT PRIVILEGES IN SCHEMA route_card GRANT ALL ON TABLES TO route_card;
ALTER DEFAULT PRIVILEGES IN SCHEMA route_card GRANT ALL ON SEQUENCES TO route_card;

-- Tables can be created by:
--   A) starting the backend (migrations_route_card.py), OR
--   B) running manually in order:
--        03_route_card_schema.sql
--        04_seed_bel_departments.sql
--        05_seed_default_admin.sql
--        06_verify_offline_install.sql  (optional check)
