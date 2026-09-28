-- OPTIONAL dedicated role (skip if using DB_USER=postgres in .env).
-- Run while connected to database "postgres" in pgAdmin Query Tool.

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'route_card') THEN
    CREATE ROLE route_card LOGIN PASSWORD 'route_card';
  END IF;
END
$$;

GRANT ALL PRIVILEGES ON DATABASE route_card TO route_card;

-- Then reconnect to database "route_card" and run:
--   GRANT ALL ON SCHEMA public TO route_card;
--   GRANT CREATE ON DATABASE route_card TO route_card;
--
-- And set backend/.env:
--   DB_USER=route_card
--   DB_PASSWORD=route_card
