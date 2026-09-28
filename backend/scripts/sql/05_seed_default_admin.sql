-- ============================================================
-- 05_seed_default_admin.sql
-- ============================================================
-- Connect to database "route_card" in pgAdmin, then run.
-- Inserts default admin only if no users exist.
--
-- Login:  empId = admin
--         password = admin123
--         dept = Software
--         role = admin
--
-- Password hash = PBKDF2-SHA256 (same scheme as backend/app/security.py).
-- ============================================================

INSERT INTO route_card.users (emp_id, name, dept, password_hash, role, is_active)
SELECT
    'admin',
    'Administrator',
    'Software',
    'pbkdf2_sha256$120000$8ec135a5853b9fa796ccfa86a4a10890$1fa5dfe60884830bacdf0ce0e3bae3de67355ca95043a1930f1d0e4dfbe4064c',
    'admin',
    TRUE
WHERE NOT EXISTS (SELECT 1 FROM route_card.users LIMIT 1);

-- Optional sample engineer (skipped if emp_id already exists):
-- INSERT INTO route_card.users (emp_id, name, dept, password_hash, role, is_active)
-- SELECT 'engineer', 'Engineer', 'MR',
--   'pbkdf2_sha256$120000$REPLACE_WITH_HASH_FROM_APP$…',
--   'engineer', TRUE
-- WHERE NOT EXISTS (SELECT 1 FROM route_card.users WHERE emp_id = 'engineer');

-- Verify:
-- SELECT id, emp_id, name, dept, role, is_active, created_at FROM route_card.users;
