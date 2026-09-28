-- pgAdmin: connect to database "postgres", open Query Tool, then run:

CREATE DATABASE route_card
  WITH OWNER = postgres
       ENCODING = 'UTF8'
       TEMPLATE = template0;

-- If it already exists, pgAdmin will error — that is fine; skip this step.
-- Schema "route_card" and tables are created automatically on first backend start.
