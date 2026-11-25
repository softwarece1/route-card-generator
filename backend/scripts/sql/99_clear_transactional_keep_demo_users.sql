-- ============================================================
-- 99_clear_transactional_keep_demo_users.sql
-- ============================================================
-- Wipe transactional workflow data. Keep masters (SBUs, depts,
-- WCs, machines, templates, refs, rules) and a small user set:
--   - admin
--   - one sbu_head per SBU: MR, MS, ADSN, NS1, NS2
--   - one dept_head per department under those SBUs (if any)
--   - up to 2 engineers per department under those SBUs (if any)
-- Run against database "route_card". Review the PREVIEW selects
-- before COMMIT (script ends with COMMIT — wrap manually if needed).
-- ============================================================

BEGIN;

SET search_path TO route_card;

CREATE TEMP TABLE keep_user_ids (id integer PRIMARY KEY) ON COMMIT DROP;

-- Admin(s)
INSERT INTO keep_user_ids (id)
SELECT id FROM users
WHERE role = 'admin' OR lower(emp_id) = 'admin'
ON CONFLICT DO NOTHING;

-- One sbu_head per keep SBU (match users.sbu to sbus.code or name)
INSERT INTO keep_user_ids (id)
SELECT DISTINCT ON (s.code) u.id
FROM users u
JOIN sbus s
  ON s.name = u.sbu OR s.code = u.sbu
WHERE u.role = 'sbu_head'
  AND u.is_active
  AND upper(s.code) IN ('MR', 'MS', 'ADSN', 'NS1', 'NS2')
ORDER BY s.code, u.id
ON CONFLICT DO NOTHING;

-- One dept_head per department in keep SBUs
INSERT INTO keep_user_ids (id)
SELECT DISTINCT ON (u.department_id) u.id
FROM users u
JOIN departments d ON d.id = u.department_id
JOIN sbus s ON s.id = d.sbu
WHERE u.role = 'dept_head'
  AND u.is_active
  AND upper(s.code) IN ('MR', 'MS', 'ADSN', 'NS1', 'NS2')
ORDER BY u.department_id, u.id
ON CONFLICT DO NOTHING;

-- Up to 2 engineers per department in keep SBUs
INSERT INTO keep_user_ids (id)
SELECT id FROM (
  SELECT u.id,
         row_number() OVER (PARTITION BY u.department_id ORDER BY u.id) AS rn
  FROM users u
  JOIN departments d ON d.id = u.department_id
  JOIN sbus s ON s.id = d.sbu
  WHERE u.role = 'engineer'
    AND u.is_active
    AND upper(s.code) IN ('MR', 'MS', 'ADSN', 'NS1', 'NS2')
) t
WHERE rn <= 2
ON CONFLICT DO NOTHING;

-- ---------- PREVIEW (also echoed after delete) ----------
-- SELECT u.id, u.emp_id, u.name, u.role, u.sbu, d.code AS dept
-- FROM users u
-- LEFT JOIN departments d ON d.id = u.department_id
-- WHERE u.id IN (SELECT id FROM keep_user_ids)
-- ORDER BY u.role, u.sbu, d.code, u.id;

-- Clear transactional / ephemeral tables (masters untouched)
TRUNCATE TABLE
  route_card.inspection_chars,
  route_card.operations,
  route_card.route_remarks,
  route_card.review_flags,
  route_card.audit_events,
  route_card.route_cards,
  route_card.extractions,
  route_card.documents,
  route_card.drawings,
  route_card.analyze_jobs,
  route_card.sessions,
  route_card.notifications,
  route_card.user_favorites,
  route_card.auth_sessions,
  route_card.password_history,
  route_card.login_challenges,
  route_card.captcha_challenges
RESTART IDENTITY CASCADE;

-- Detach master rows from users we will delete
UPDATE operation_templates t
SET created_by = NULL
WHERE created_by IS NOT NULL
  AND created_by NOT IN (SELECT id FROM keep_user_ids);

UPDATE few_shot_examples f
SET created_by = NULL
WHERE created_by IS NOT NULL
  AND created_by NOT IN (SELECT id FROM keep_user_ids);

-- Break reporting / approval edges before user delete
UPDATE users
SET reports_to = NULL
WHERE reports_to IS NOT NULL
  AND reports_to NOT IN (SELECT id FROM keep_user_ids);

UPDATE users
SET reports_to = NULL
WHERE id NOT IN (SELECT id FROM keep_user_ids);

UPDATE users
SET approval_decided_by = NULL
WHERE approval_decided_by IS NOT NULL
  AND (
    approval_decided_by NOT IN (SELECT id FROM keep_user_ids)
    OR id NOT IN (SELECT id FROM keep_user_ids)
  );

DELETE FROM users
WHERE id NOT IN (SELECT id FROM keep_user_ids);

-- Ensure kept non-admins still point at a valid manager when possible
-- (no-op if already null / valid)

COMMIT;

-- Verify:
-- SELECT role, count(*) FROM route_card.users GROUP BY role ORDER BY 1;
-- SELECT emp_id, name, role, sbu, department_id FROM route_card.users ORDER BY role, sbu, id;
-- SELECT count(*) AS sessions FROM route_card.sessions;
-- SELECT count(*) AS route_cards FROM route_card.route_cards;
