"""Route-card schema migrations — sessions / documents / drawings.session column."""

import psycopg2

from ..config.settings import settings

# Fixed DDL only — no string-interpolated identifiers (Bandit B608).
_RENAME_DEPT_TO_SBU_SQL = {
    "users": """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'route_card' AND table_name = 'users'
              AND column_name = 'dept'
          ) AND NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'route_card' AND table_name = 'users'
              AND column_name = 'sbu'
          ) THEN
            ALTER TABLE route_card.users RENAME COLUMN dept TO sbu;
          END IF;
        END $$;
        """,
    "operation_templates": """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'route_card' AND table_name = 'operation_templates'
              AND column_name = 'dept'
          ) AND NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'route_card' AND table_name = 'operation_templates'
              AND column_name = 'sbu'
          ) THEN
            ALTER TABLE route_card.operation_templates RENAME COLUMN dept TO sbu;
          END IF;
        END $$;
        """,
    "few_shot_examples": """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'route_card' AND table_name = 'few_shot_examples'
              AND column_name = 'dept'
          ) AND NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'route_card' AND table_name = 'few_shot_examples'
              AND column_name = 'sbu'
          ) THEN
            ALTER TABLE route_card.few_shot_examples RENAME COLUMN dept TO sbu;
          END IF;
        END $$;
        """,
    "work_centers": """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'route_card' AND table_name = 'work_centers'
              AND column_name = 'dept'
          ) AND NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'route_card' AND table_name = 'work_centers'
              AND column_name = 'sbu'
          ) THEN
            ALTER TABLE route_card.work_centers RENAME COLUMN dept TO sbu;
          END IF;
        END $$;
        """,
    "machines": """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'route_card' AND table_name = 'machines'
              AND column_name = 'dept'
          ) AND NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'route_card' AND table_name = 'machines'
              AND column_name = 'sbu'
          ) THEN
            ALTER TABLE route_card.machines RENAME COLUMN dept TO sbu;
          END IF;
        END $$;
        """,
}


def _rename_dept_to_sbu_columns(cursor) -> None:
    for sql in _RENAME_DEPT_TO_SBU_SQL.values():
        cursor.execute(sql)


def run_migrations():
    conn = psycopg2.connect(
        dbname=settings.DB_NAME,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        host=settings.DB_HOST,
        port=settings.DB_PORT,
    )
    conn.autocommit = True
    cursor = conn.cursor()

    try:
        cursor.execute("CREATE SCHEMA IF NOT EXISTS route_card;")

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS route_card.users (
                id SERIAL PRIMARY KEY,
                emp_id VARCHAR(64) NOT NULL UNIQUE,
                name VARCHAR(255) NOT NULL,
                sbu VARCHAR(128) NOT NULL DEFAULT '',
                password_hash TEXT NOT NULL,
                role VARCHAR(32) NOT NULL DEFAULT 'engineer',
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
            );
            """
        )

        cursor.execute(
            """
            ALTER TABLE route_card.users
            ADD COLUMN IF NOT EXISTS sbu VARCHAR(128) NOT NULL DEFAULT '';
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS route_card.sessions (
                id SERIAL PRIMARY KEY,
                status VARCHAR(32) NOT NULL DEFAULT 'open',
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
            );
            """
        )

        cursor.execute(
            """
            ALTER TABLE route_card.sessions
            ADD COLUMN IF NOT EXISTS "user" INTEGER
            REFERENCES route_card.users(id)
            ON DELETE SET NULL;
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS route_card.drawings (
                id SERIAL PRIMARY KEY,
                filename VARCHAR(255) NOT NULL,
                file_type VARCHAR(32) NOT NULL,
                content_type VARCHAR(128),
                object_path TEXT NOT NULL,
                storage_backend VARCHAR(64) NOT NULL DEFAULT 'minio',
                size_bytes INTEGER NOT NULL DEFAULT 0,
                pages INTEGER,
                status VARCHAR(32) NOT NULL DEFAULT 'uploaded',
                drawing_type VARCHAR(32) DEFAULT 'unknown',
                uploaded_by VARCHAR(128),
                error_message TEXT,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
            );
            """
        )

        cursor.execute(
            """
            ALTER TABLE route_card.drawings
            ADD COLUMN IF NOT EXISTS session INTEGER
            REFERENCES route_card.sessions(id)
            ON DELETE SET NULL;
            """
        )

        cursor.execute(
            """
            ALTER TABLE route_card.drawings
            ADD COLUMN IF NOT EXISTS "user" INTEGER
            REFERENCES route_card.users(id)
            ON DELETE SET NULL;
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS route_card.documents (
                id SERIAL PRIMARY KEY,
                session INTEGER NOT NULL
                    REFERENCES route_card.sessions(id) ON DELETE CASCADE,
                role VARCHAR(32) NOT NULL,
                filename VARCHAR(255) NOT NULL,
                file_type VARCHAR(32) NOT NULL,
                content_type VARCHAR(128),
                object_path TEXT NOT NULL,
                storage_backend VARCHAR(64) NOT NULL DEFAULT 'minio',
                size_bytes INTEGER NOT NULL DEFAULT 0,
                status VARCHAR(32) NOT NULL DEFAULT 'uploaded',
                extraction JSONB,
                warnings JSONB,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS route_card.extractions (
                id SERIAL PRIMARY KEY,
                drawing INTEGER NOT NULL
                    REFERENCES route_card.drawings(id) ON DELETE CASCADE,
                title_block JSONB,
                revisions JSONB,
                bom_items JSONB,
                notes JSONB,
                torque_specs JSONB,
                dimensions JSONB,
                "references" JSONB,
                warnings JSONB,
                raw_text TEXT,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS route_card.route_cards (
                id SERIAL PRIMARY KEY,
                drawing INTEGER NOT NULL
                    REFERENCES route_card.drawings(id) ON DELETE CASCADE,
                status VARCHAR(32) NOT NULL DEFAULT 'draft',
                part_info JSONB,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS route_card.operations (
                id SERIAL PRIMARY KEY,
                route_card INTEGER NOT NULL
                    REFERENCES route_card.route_cards(id) ON DELETE CASCADE,
                op_no INTEGER NOT NULL,
                operation VARCHAR(512) NOT NULL,
                work_centre VARCHAR(128),
                machine VARCHAR(128),
                tool VARCHAR(256),
                items_used JSONB,
                torque_spec VARCHAR(256),
                reference VARCHAR(512),
                setup VARCHAR(32),
                time VARCHAR(64),
                inspection VARCHAR(256),
                instruction_text TEXT,
                status VARCHAR(32) NOT NULL DEFAULT 'Planned'
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS route_card.inspection_chars (
                id SERIAL PRIMARY KEY,
                route_card INTEGER NOT NULL
                    REFERENCES route_card.route_cards(id) ON DELETE CASCADE,
                characteristic VARCHAR(512) NOT NULL,
                nominal VARCHAR(256),
                tolerance VARCHAR(256),
                method VARCHAR(256),
                frequency VARCHAR(128),
                criticality VARCHAR(64),
                source VARCHAR(256)
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS route_card.sbus (
                id SERIAL PRIMARY KEY,
                code VARCHAR(64) NOT NULL UNIQUE,
                name VARCHAR(128) NOT NULL,
                plant_id VARCHAR(32) NOT NULL DEFAULT '',
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                sort_order INTEGER NOT NULL DEFAULT 0,
                work_center_synced_at TIMESTAMP WITHOUT TIME ZONE,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS route_card.operation_templates (
                id SERIAL PRIMARY KEY,
                sbu VARCHAR(128) NOT NULL,
                name VARCHAR(255) NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                placement VARCHAR(16) NOT NULL DEFAULT 'any',
                created_by INTEGER
                    REFERENCES route_card.users(id) ON DELETE SET NULL,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                is_active BOOLEAN NOT NULL DEFAULT TRUE
            );
            """
        )

        # Early dept→sbu column renames so subsequent indexes use the new names
        _rename_dept_to_sbu_columns(cursor)

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_operation_templates_sbu_active
            ON route_card.operation_templates (sbu, is_active);
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS route_card.operation_template_steps (
                id SERIAL PRIMARY KEY,
                template INTEGER NOT NULL
                    REFERENCES route_card.operation_templates(id) ON DELETE CASCADE,
                sort_order INTEGER NOT NULL DEFAULT 0,
                operation VARCHAR(512) NOT NULL,
                work_centre VARCHAR(128) NOT NULL DEFAULT '',
                setup VARCHAR(32) NOT NULL DEFAULT '',
                time VARCHAR(64) NOT NULL DEFAULT '',
                instruction_text TEXT,
                inspection VARCHAR(256) NOT NULL DEFAULT '',
                machine VARCHAR(128) NOT NULL DEFAULT '',
                tool VARCHAR(256) NOT NULL DEFAULT '',
                generates_output_serial BOOLEAN NOT NULL DEFAULT FALSE,
                requires_input_material BOOLEAN NOT NULL DEFAULT FALSE,
                manual_operation BOOLEAN NOT NULL DEFAULT TRUE
            );
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_operation_template_steps_template
            ON route_card.operation_template_steps (template, sort_order);
            """
        )

        cursor.execute(
            """
            ALTER TABLE route_card.operation_templates
            ADD COLUMN IF NOT EXISTS copied_from_id INTEGER NULL;
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_operation_templates_copied_from
            ON route_card.operation_templates (sbu, copied_from_id)
            WHERE copied_from_id IS NOT NULL AND is_active = TRUE;
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS route_card.analyze_jobs (
                id SERIAL PRIMARY KEY,
                session INTEGER NOT NULL
                    REFERENCES route_card.sessions(id) ON DELETE CASCADE,
                "user" INTEGER
                    REFERENCES route_card.users(id) ON DELETE SET NULL,
                status VARCHAR(32) NOT NULL DEFAULT 'queued',
                progress INTEGER NOT NULL DEFAULT 0,
                message TEXT NOT NULL DEFAULT '',
                error_message TEXT,
                vlm_page_indexes JSONB,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                started_at TIMESTAMP WITHOUT TIME ZONE,
                finished_at TIMESTAMP WITHOUT TIME ZONE
            );
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_analyze_jobs_status_created
            ON route_card.analyze_jobs (status, created_at);
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS route_card.review_flags (
                id SERIAL PRIMARY KEY,
                session INTEGER
                    REFERENCES route_card.sessions(id) ON DELETE CASCADE,
                route_card INTEGER
                    REFERENCES route_card.route_cards(id) ON DELETE CASCADE,
                "user" INTEGER
                    REFERENCES route_card.users(id) ON DELETE SET NULL,
                kind VARCHAR(64) NOT NULL,
                severity VARCHAR(16) NOT NULL DEFAULT 'medium',
                message TEXT NOT NULL,
                source VARCHAR(128) NOT NULL DEFAULT '',
                resolved BOOLEAN NOT NULL DEFAULT FALSE,
                resolved_at TIMESTAMP WITHOUT TIME ZONE,
                resolved_by VARCHAR(128),
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
            );
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_review_flags_route_resolved
            ON route_card.review_flags (route_card, resolved);
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS route_card.audit_events (
                id SERIAL PRIMARY KEY,
                route_card INTEGER
                    REFERENCES route_card.route_cards(id) ON DELETE CASCADE,
                session INTEGER,
                "user" INTEGER
                    REFERENCES route_card.users(id) ON DELETE SET NULL,
                action VARCHAR(64) NOT NULL,
                detail JSONB,
                comment TEXT,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS route_card.notifications (
                id SERIAL PRIMARY KEY,
                "user" INTEGER NOT NULL
                    REFERENCES route_card.users(id) ON DELETE CASCADE,
                title VARCHAR(255) NOT NULL,
                body TEXT NOT NULL DEFAULT '',
                link VARCHAR(512) NOT NULL DEFAULT '',
                read_at TIMESTAMP WITHOUT TIME ZONE,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
            );
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_notifications_user_created
            ON route_card.notifications ("user", created_at DESC);
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS route_card.auth_sessions (
                id SERIAL PRIMARY KEY,
                "user" INTEGER NOT NULL
                    REFERENCES route_card.users(id) ON DELETE CASCADE,
                access_jti VARCHAR(64) NOT NULL UNIQUE,
                user_agent VARCHAR(512) NOT NULL DEFAULT '',
                ip VARCHAR(64) NOT NULL DEFAULT '',
                expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
                revoked_at TIMESTAMP WITHOUT TIME ZONE,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                last_seen_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
            );
            """
        )
        # Legacy auth_sessions (jti / ip_address / last_activity_at) → current model.
        # CREATE TABLE IF NOT EXISTS does not alter an already-existing older table.
        cursor.execute(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'route_card'
                      AND table_name = 'auth_sessions'
                      AND column_name = 'jti'
                ) AND NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'route_card'
                      AND table_name = 'auth_sessions'
                      AND column_name = 'access_jti'
                ) THEN
                    ALTER TABLE route_card.auth_sessions
                        RENAME COLUMN jti TO access_jti;
                END IF;

                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'route_card'
                      AND table_name = 'auth_sessions'
                      AND column_name = 'ip_address'
                ) AND NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'route_card'
                      AND table_name = 'auth_sessions'
                      AND column_name = 'ip'
                ) THEN
                    ALTER TABLE route_card.auth_sessions
                        RENAME COLUMN ip_address TO ip;
                END IF;

                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'route_card'
                      AND table_name = 'auth_sessions'
                      AND column_name = 'last_activity_at'
                ) AND NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'route_card'
                      AND table_name = 'auth_sessions'
                      AND column_name = 'last_seen_at'
                ) THEN
                    ALTER TABLE route_card.auth_sessions
                        RENAME COLUMN last_activity_at TO last_seen_at;
                END IF;
            END $$;
            """
        )
        cursor.execute(
            """
            ALTER TABLE route_card.auth_sessions
            ADD COLUMN IF NOT EXISTS access_jti VARCHAR(64);
            """
        )
        cursor.execute(
            """
            ALTER TABLE route_card.auth_sessions
            ADD COLUMN IF NOT EXISTS user_agent VARCHAR(512) NOT NULL DEFAULT '';
            """
        )
        cursor.execute(
            """
            ALTER TABLE route_card.auth_sessions
            ADD COLUMN IF NOT EXISTS ip VARCHAR(64) NOT NULL DEFAULT '';
            """
        )
        cursor.execute(
            """
            ALTER TABLE route_card.auth_sessions
            ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP WITHOUT TIME ZONE;
            """
        )
        cursor.execute(
            """
            ALTER TABLE route_card.auth_sessions
            ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMP WITHOUT TIME ZONE;
            """
        )
        cursor.execute(
            """
            ALTER TABLE route_card.auth_sessions
            ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITHOUT TIME ZONE
                NOT NULL DEFAULT NOW();
            """
        )
        cursor.execute(
            """
            ALTER TABLE route_card.auth_sessions
            ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP WITHOUT TIME ZONE
                NOT NULL DEFAULT NOW();
            """
        )
        # Backfill / tighten access_jti when added empty on a broken legacy table
        cursor.execute(
            """
            UPDATE route_card.auth_sessions
            SET access_jti = 'legacy-' || id::text
            WHERE access_jti IS NULL OR btrim(access_jti) = '';
            """
        )
        cursor.execute(
            """
            DO $$
            BEGIN
                BEGIN
                    ALTER TABLE route_card.auth_sessions
                        ALTER COLUMN access_jti SET NOT NULL;
                EXCEPTION WHEN others THEN
                    NULL;
                END;
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'auth_sessions_access_jti_key'
                ) THEN
                    BEGIN
                        ALTER TABLE route_card.auth_sessions
                            ADD CONSTRAINT auth_sessions_access_jti_key UNIQUE (access_jti);
                    EXCEPTION WHEN others THEN
                        NULL;
                    END;
                END IF;
            END $$;
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_auth_sessions_user_active
            ON route_card.auth_sessions ("user", revoked_at);
            """
        )
        # Legacy partial unique index keys on is_active; keep column in sync with revoked_at.
        # Order matters: sync + dedupe BEFORE creating uq_auth_sessions_one_active_user.
        cursor.execute(
            """
            ALTER TABLE route_card.auth_sessions
            ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;
            """
        )
        cursor.execute(
            """
            UPDATE route_card.auth_sessions
            SET is_active = FALSE
            WHERE revoked_at IS NOT NULL AND is_active IS TRUE;
            """
        )
        cursor.execute(
            """
            UPDATE route_card.auth_sessions
            SET is_active = TRUE
            WHERE revoked_at IS NULL AND is_active IS FALSE;
            """
        )
        # Only one active row per user. Collapse duplicates before unique index.
        cursor.execute(
            """
            WITH ranked AS (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY "user"
                           ORDER BY COALESCE(last_seen_at, created_at) DESC NULLS LAST, id DESC
                       ) AS rn
                FROM route_card.auth_sessions
                WHERE is_active IS TRUE OR revoked_at IS NULL
            )
            UPDATE route_card.auth_sessions s
            SET is_active = FALSE,
                revoked_at = COALESCE(s.revoked_at, NOW())
            FROM ranked r
            WHERE s.id = r.id AND r.rn > 1;
            """
        )
        cursor.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_auth_sessions_one_active_user
            ON route_card.auth_sessions ("user") WHERE is_active;
            """
        )

        # Self-service signup approval (engineer → sbu_head / admin)
        cursor.execute(
            """
            ALTER TABLE route_card.users
            ADD COLUMN IF NOT EXISTS approval_status VARCHAR(32) NOT NULL DEFAULT 'approved';
            """
        )
        cursor.execute(
            """
            ALTER TABLE route_card.users
            ADD COLUMN IF NOT EXISTS approval_remark TEXT NOT NULL DEFAULT '';
            """
        )
        cursor.execute(
            """
            ALTER TABLE route_card.users
            ADD COLUMN IF NOT EXISTS approval_decided_at TIMESTAMP WITHOUT TIME ZONE;
            """
        )
        cursor.execute(
            """
            ALTER TABLE route_card.users
            ADD COLUMN IF NOT EXISTS approval_decided_by INTEGER
                REFERENCES route_card.users(id) ON DELETE SET NULL;
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_users_approval_status_sbu
            ON route_card.users (approval_status, sbu);
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS route_card.user_favorites (
                id SERIAL PRIMARY KEY,
                "user" INTEGER NOT NULL
                    REFERENCES route_card.users(id) ON DELETE CASCADE,
                part_number VARCHAR(128) NOT NULL DEFAULT '',
                label VARCHAR(255) NOT NULL DEFAULT '',
                session_id INTEGER,
                route_card_id INTEGER,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS route_card.sbu_rules (
                id SERIAL PRIMARY KEY,
                sbu VARCHAR(128) NOT NULL UNIQUE,
                rules JSONB,
                updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                updated_by VARCHAR(128)
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS route_card.few_shot_examples (
                id SERIAL PRIMARY KEY,
                sbu VARCHAR(128) NOT NULL,
                doc_type VARCHAR(32) NOT NULL DEFAULT 'drawing',
                title VARCHAR(255) NOT NULL,
                input_excerpt TEXT,
                output_excerpt TEXT NOT NULL,
                created_by INTEGER
                    REFERENCES route_card.users(id) ON DELETE SET NULL,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                is_active BOOLEAN NOT NULL DEFAULT TRUE
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS route_card.machines (
                id SERIAL PRIMARY KEY,
                plant VARCHAR(128) NOT NULL DEFAULT '',
                work_centre VARCHAR(128) NOT NULL,
                name VARCHAR(255) NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
            );
            """
        )

        cursor.execute(
            """
            ALTER TABLE route_card.users
            ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE;
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS route_card.password_history (
                id SERIAL PRIMARY KEY,
                "user" INTEGER NOT NULL
                    REFERENCES route_card.users(id) ON DELETE CASCADE,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
            );
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_password_history_user_created
            ON route_card.password_history ("user", created_at DESC);
            """
        )

        # Work centres master + machine / operation link columns
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS route_card.work_centers (
                id SERIAL PRIMARY KEY,
                sbu VARCHAR(128) NOT NULL DEFAULT '',
                code VARCHAR(64) NOT NULL,
                name VARCHAR(255) NOT NULL,
                mode VARCHAR(32) NOT NULL DEFAULT 'hybrid',
                is_shared BOOLEAN NOT NULL DEFAULT FALSE,
                plant VARCHAR(128) NOT NULL DEFAULT '',
                sap_code VARCHAR(128) NOT NULL DEFAULT '',
                capability_tags JSONB,
                match_keywords JSONB,
                default_tool VARCHAR(256) NOT NULL DEFAULT '',
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
            );
            """
        )
        cursor.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_work_centers_shared_code
            ON route_card.work_centers (code)
            WHERE is_shared = TRUE AND is_active = TRUE;
            """
        )
        # Legacy uniqueness was (dept, code); plant-scoped masters need (plant, code)
        cursor.execute("DROP INDEX IF EXISTS route_card.ux_work_centers_dept_code;")
        cursor.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_work_centers_plant_code
            ON route_card.work_centers (plant, code)
            WHERE is_active = TRUE AND COALESCE(plant, '') <> '';
            """
        )
        cursor.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_work_centers_sbu_code
            ON route_card.work_centers (sbu, code)
            WHERE is_shared = FALSE AND is_active = TRUE
              AND COALESCE(plant, '') = '';
            """
        )
        cursor.execute(
            """
            ALTER TABLE route_card.machines
            ADD COLUMN IF NOT EXISTS work_center INTEGER
                REFERENCES route_card.work_centers(id) ON DELETE SET NULL;
            """
        )
        cursor.execute(
            """
            ALTER TABLE route_card.machines
            ADD COLUMN IF NOT EXISTS sbu VARCHAR(128) NOT NULL DEFAULT '';
            """
        )
        cursor.execute(
            """
            ALTER TABLE route_card.machines
            ADD COLUMN IF NOT EXISTS code VARCHAR(64) NOT NULL DEFAULT '';
            """
        )
        cursor.execute(
            """
            ALTER TABLE route_card.machines
            ADD COLUMN IF NOT EXISTS sap_code VARCHAR(128) NOT NULL DEFAULT '';
            """
        )
        cursor.execute(
            """
            ALTER TABLE route_card.machines
            ADD COLUMN IF NOT EXISTS capability_tags JSONB;
            """
        )
        cursor.execute(
            """
            ALTER TABLE route_card.machines
            ADD COLUMN IF NOT EXISTS is_manual_placeholder BOOLEAN NOT NULL DEFAULT FALSE;
            """
        )
        for col, typ in [
            ("work_centre_id", "INTEGER"),
            ("machine_id", "INTEGER"),
            ("link_status", "VARCHAR(32) NOT NULL DEFAULT ''"),
            ("link_confidence", "DOUBLE PRECISION"),
        ]:
            cursor.execute(
                f"""
                ALTER TABLE route_card.operations
                ADD COLUMN IF NOT EXISTS {col} {typ};
                """
            )

        for col, typ in [
            ("ied_shared_at", "TIMESTAMP"),
            ("ied_shared_by_id", "INTEGER"),
            ("ied_completed_at", "TIMESTAMP"),
            ("ied_completed_by_id", "INTEGER"),
        ]:
            cursor.execute(
                f"""
                ALTER TABLE route_card.route_cards
                ADD COLUMN IF NOT EXISTS {col} {typ};
                """
            )

        # Pony maps Required(RcRouteCard) -> column "route_card" (not route_card_id)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS route_card.route_remarks (
                id SERIAL PRIMARY KEY,
                route_card INTEGER NOT NULL
                    REFERENCES route_card.route_cards(id) ON DELETE CASCADE,
                "user" INTEGER
                    REFERENCES route_card.users(id) ON DELETE SET NULL,
                body TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            );
            """
        )
        # Repair early draft that used route_card_id / user_id
        cursor.execute(
            """
            DO $$
            BEGIN
              IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'route_card'
                  AND table_name = 'route_remarks'
                  AND column_name = 'route_card_id'
              ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'route_card'
                  AND table_name = 'route_remarks'
                  AND column_name = 'route_card'
              ) THEN
                ALTER TABLE route_card.route_remarks
                  RENAME COLUMN route_card_id TO route_card;
              END IF;
              IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'route_card'
                  AND table_name = 'route_remarks'
                  AND column_name = 'user_id'
              ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'route_card'
                  AND table_name = 'route_remarks'
                  AND column_name = 'user'
              ) THEN
                ALTER TABLE route_card.route_remarks
                  RENAME COLUMN user_id TO "user";
              END IF;
            END $$;
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_route_remarks_card
            ON route_card.route_remarks (route_card, created_at);
            """
        )

        # Reporting officer (engineer → sbu_head)
        cursor.execute(
            """
            ALTER TABLE route_card.users
            ADD COLUMN IF NOT EXISTS reports_to INTEGER
                REFERENCES route_card.users(id) ON DELETE SET NULL;
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_users_reports_to
            ON route_card.users (reports_to);
            """
        )

        print("route_card migrations applied")

        # SBU plant_id (SAP WERKS) — seed runs after rename block so target is always sbus
        dummy_plant_codes = [
            "1100", "1200", "1300", "1400", "1500", "1600", "1700", "1800",
            "1900", "2000", "2100", "2200", "2300", "2400", "2500", "2600",
            "2700", "2800", "2900", "3000",
        ]
        bel_sbus = [
            ("MR", "MR", 10),
            ("MS", "MS", 20),
            ("ARMS_AMMO", "Arms & Ammunition", 30),
            ("NS1", "NS1", 40),
            ("NS2", "NS2", 50),
            ("ADSN", "ADSN", 60),
            ("MCE_NCS", "MCE/NCS", 70),
            ("NWCS", "NWCS", 80),
            ("SC", "SC", 90),
            ("US", "US", 100),
            ("HLS", "HLS", 110),
            ("EW_A", "EW&A", 120),
            ("SEEKERS", "Seekers (RF & IR)", 130),
            ("EM", "EM", 140),
            ("COMPONENTS", "Components", 150),
            ("SOFTWARE", "Software", 160),
            ("AF", "A&F", 170),
            ("ES", "ES", 180),
            ("CSG", "CSG", 190),
            ("CUSTOMER", "Customer", 200),
        ]
        # Admin plant override for queued analyze jobs (WC linking)
        cursor.execute(
            """
            ALTER TABLE route_card.analyze_jobs
            ADD COLUMN IF NOT EXISTS plant VARCHAR(32) NULL;
            """
        )

        # Shared company reference library (PS / DS / SS = categories)
        # Pony maps Required(RcRefFolder) → column name "folder" (not folder_id).
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS route_card.ref_folders (
                id SERIAL PRIMARY KEY,
                code VARCHAR(16) NOT NULL UNIQUE,
                name VARCHAR(255) NOT NULL DEFAULT '',
                created_by VARCHAR(128) NOT NULL DEFAULT '',
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
            );
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS route_card.ref_documents (
                id SERIAL PRIMARY KEY,
                folder INTEGER NOT NULL
                    REFERENCES route_card.ref_folders(id) ON DELETE CASCADE,
                doc_code VARCHAR(32) NOT NULL,
                original_filename VARCHAR(255) NOT NULL,
                object_path TEXT NOT NULL,
                storage_backend VARCHAR(64) NOT NULL DEFAULT 'minio',
                content_type VARCHAR(128) NOT NULL DEFAULT 'application/pdf',
                size_bytes INTEGER NOT NULL DEFAULT 0,
                uploaded_by VARCHAR(128) NOT NULL DEFAULT '',
                version_number INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                UNIQUE (folder, doc_code)
            );
            """
        )
        # Repair early migration that used folder_id (breaks Pony FK "folder")
        cursor.execute(
            """
            DO $$
            BEGIN
              IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'route_card'
                  AND table_name = 'ref_documents'
                  AND column_name = 'folder_id'
              ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'route_card'
                  AND table_name = 'ref_documents'
                  AND column_name = 'folder'
              ) THEN
                ALTER TABLE route_card.ref_documents
                  RENAME COLUMN folder_id TO folder;
              END IF;
            END $$;
            """
        )
        cursor.execute(
            """
            ALTER TABLE route_card.ref_documents
            ADD COLUMN IF NOT EXISTS version_number INTEGER NOT NULL DEFAULT 1;
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS route_card.ref_document_versions (
                id SERIAL PRIMARY KEY,
                document INTEGER NOT NULL
                    REFERENCES route_card.ref_documents(id) ON DELETE CASCADE,
                version_number INTEGER NOT NULL,
                original_filename VARCHAR(255) NOT NULL,
                object_path TEXT NOT NULL,
                storage_backend VARCHAR(64) NOT NULL DEFAULT 'minio',
                content_type VARCHAR(128) NOT NULL DEFAULT 'application/pdf',
                size_bytes INTEGER NOT NULL DEFAULT 0,
                uploaded_by VARCHAR(128) NOT NULL DEFAULT '',
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                UNIQUE (document, version_number)
            );
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_ref_documents_doc_code
            ON route_card.ref_documents (doc_code);
            """
        )
        # Backfill v1 rows for docs that have no version history yet
        cursor.execute(
            """
            INSERT INTO route_card.ref_document_versions (
                document, version_number, original_filename, object_path,
                storage_backend, content_type, size_bytes, uploaded_by, created_at
            )
            SELECT
                d.id,
                COALESCE(d.version_number, 1),
                d.original_filename,
                d.object_path,
                d.storage_backend,
                COALESCE(d.content_type, 'application/pdf'),
                d.size_bytes,
                COALESCE(d.uploaded_by, ''),
                d.created_at
            FROM route_card.ref_documents d
            WHERE NOT EXISTS (
                SELECT 1 FROM route_card.ref_document_versions v
                WHERE v.document = d.id
            );
            """
        )

        # --- dept → SBU rename; drop plants; stub departments under SBU ---
        cursor.execute(
            """
            DO $$
            BEGIN
              -- Rename legacy SBU master departments → sbus
              IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'route_card' AND table_name = 'departments'
              ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'route_card' AND table_name = 'sbus'
              ) THEN
                ALTER TABLE route_card.departments RENAME TO sbus;
              END IF;

              -- Leftover legacy departments (code/name master, no sbu FK) while sbus already exists
              IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'route_card' AND table_name = 'departments'
              ) AND EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'route_card' AND table_name = 'sbus'
              ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'route_card' AND table_name = 'departments'
                  AND column_name = 'sbu'
                  AND data_type IN ('integer', 'bigint')
              ) THEN
                -- Copy any rows not already in sbus, then drop legacy table
                INSERT INTO route_card.sbus (code, name, is_active, sort_order)
                SELECT d.code, d.name,
                       COALESCE(d.is_active, TRUE),
                       COALESCE(d.sort_order, 0)
                FROM route_card.departments d
                WHERE NOT EXISTS (
                  SELECT 1 FROM route_card.sbus s WHERE s.code = d.code
                );
                DROP TABLE route_card.departments;
              END IF;

              -- Copy plant sync stamp onto sbus before dropping plants
              IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'route_card' AND table_name = 'plants'
              ) AND EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'route_card' AND table_name = 'sbus'
              ) THEN
                IF NOT EXISTS (
                  SELECT 1 FROM information_schema.columns
                  WHERE table_schema = 'route_card' AND table_name = 'sbus'
                    AND column_name = 'work_center_synced_at'
                ) THEN
                  ALTER TABLE route_card.sbus
                    ADD COLUMN work_center_synced_at TIMESTAMP WITHOUT TIME ZONE;
                END IF;
                UPDATE route_card.sbus s
                SET work_center_synced_at = p.work_center_synced_at
                FROM route_card.plants p
                WHERE (s.plant_id IS NOT NULL AND s.plant_id <> '')
                  AND s.plant_id = p.code
                  AND p.work_center_synced_at IS NOT NULL
                  AND s.work_center_synced_at IS NULL;
              END IF;

              IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'route_card' AND table_name = 'plants'
              ) THEN
                DROP TABLE route_card.plants;
              END IF;
            END $$;
            """
        )

        # Ensure sbus exists + plant_id / sync columns
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS route_card.sbus (
                id SERIAL PRIMARY KEY,
                code VARCHAR(64) NOT NULL UNIQUE,
                name VARCHAR(128) NOT NULL,
                plant_id VARCHAR(32) NOT NULL DEFAULT '',
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                sort_order INTEGER NOT NULL DEFAULT 0,
                work_center_synced_at TIMESTAMP WITHOUT TIME ZONE,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
            );
            """
        )
        cursor.execute(
            """
            ALTER TABLE route_card.sbus
            ADD COLUMN IF NOT EXISTS plant_id VARCHAR(32) NOT NULL DEFAULT '';
            """
        )
        cursor.execute(
            """
            ALTER TABLE route_card.sbus
            ADD COLUMN IF NOT EXISTS work_center_synced_at TIMESTAMP WITHOUT TIME ZONE;
            """
        )

        # Rename dept → sbu columns on related tables (idempotent static DDL)
        _rename_dept_to_sbu_columns(cursor)

        # dept_rules → sbu_rules (+ column dept → sbu)
        cursor.execute(
            """
            DO $$
            BEGIN
              IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'route_card' AND table_name = 'dept_rules'
              ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'route_card' AND table_name = 'sbu_rules'
              ) THEN
                ALTER TABLE route_card.dept_rules RENAME TO sbu_rules;
              END IF;
              IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'route_card' AND table_name = 'sbu_rules'
                  AND column_name = 'dept'
              ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'route_card' AND table_name = 'sbu_rules'
                  AND column_name = 'sbu'
              ) THEN
                ALTER TABLE route_card.sbu_rules RENAME COLUMN dept TO sbu;
              END IF;
            END $$;
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS route_card.sbu_rules (
                id SERIAL PRIMARY KEY,
                sbu VARCHAR(128) NOT NULL UNIQUE,
                rules JSONB,
                updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                updated_by VARCHAR(128)
            );
            """
        )

        # NOTE: Do not rewrite role=dept_head → sbu_head on every migrate.
        # dept_head is a supported persona (user managers / reporting lines).

        # New empty departments stub under SBU
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS route_card.departments (
                id SERIAL PRIMARY KEY,
                sbu INTEGER NOT NULL
                    REFERENCES route_card.sbus(id) ON DELETE CASCADE,
                code VARCHAR(64) NOT NULL,
                name VARCHAR(128) NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                UNIQUE (sbu, code)
            );
            """
        )

        # Seed / upsert BEL SBU master (safe to re-run; BG excluded)
        bel_codes = [c for c, _, _ in bel_sbus]
        for code, name, sort_order in bel_sbus:
            cursor.execute(
                """
                INSERT INTO route_card.sbus (code, name, plant_id, is_active, sort_order)
                VALUES (%s, %s, '', TRUE, %s)
                ON CONFLICT (code) DO UPDATE
                SET name = EXCLUDED.name,
                    is_active = TRUE,
                    sort_order = EXCLUDED.sort_order;
                """,
                (code, name, sort_order),
            )
        cursor.execute(
            """
            UPDATE route_card.sbus
            SET plant_id = ''
            WHERE plant_id = ANY(%s);
            """,
            (dummy_plant_codes,),
        )
        cursor.execute(
            """
            UPDATE route_card.sbus
            SET is_active = FALSE
            WHERE code <> ALL(%s);
            """,
            (bel_codes,),
        )
        print(
            "migrated departments→sbus, dept→sbu columns; "
            "dropped plants; stubbed departments; seeded BEL sbus"
        )

        # Seed admin only when an initial password is provided. Never embed one.
        cursor.execute("SELECT COUNT(*) FROM route_card.users;")
        count = cursor.fetchone()[0]
        if count == 0:
            from app.password_policy import validate_password_complexity
            from app.security import hash_password

            initial = (getattr(settings, "ADMIN_INITIAL_PASSWORD", "") or "").strip()
            if not initial:
                print(
                    "no users yet; set ADMIN_INITIAL_PASSWORD to create the admin account"
                )
            else:
                validate_password_complexity(initial)
                cursor.execute(
                    """
                    INSERT INTO route_card.users (
                        emp_id, name, sbu, password_hash, role, is_active, must_change_password
                    )
                    VALUES (%s, %s, %s, %s, %s, TRUE, TRUE);
                    """,
                    ("admin", "Administrator", "Software", hash_password(initial), "admin"),
                )
                print("seeded admin user (empId=admin); password change required at first login")

        # --- Departments live under SBU; users.department_id; retire ied role ---
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS route_card.departments (
                id SERIAL PRIMARY KEY,
                sbu INTEGER NOT NULL
                    REFERENCES route_card.sbus(id) ON DELETE CASCADE,
                code VARCHAR(64) NOT NULL,
                name VARCHAR(128) NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                UNIQUE (sbu, code)
            );
            """
        )
        cursor.execute(
            """
            ALTER TABLE route_card.users
            ADD COLUMN IF NOT EXISTS department_id INTEGER
                REFERENCES route_card.departments(id) ON DELETE SET NULL;
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_users_department_id
            ON route_card.users (department_id);
            """
        )
        # Seed PMG + IED for every SBU
        cursor.execute(
            """
            INSERT INTO route_card.departments (sbu, code, name, is_active, sort_order)
            SELECT s.id, v.code, v.name, TRUE, v.sort_order
            FROM route_card.sbus s
            CROSS JOIN (VALUES
                ('PMG', 'PMG', 10),
                ('IED', 'IED', 20)
            ) AS v(code, name, sort_order)
            WHERE NOT EXISTS (
                SELECT 1 FROM route_card.departments d
                WHERE d.sbu = s.id AND d.code = v.code
            );
            """
        )
        # Former ied-role users → engineer in that SBU's IED department
        cursor.execute(
            """
            UPDATE route_card.users u
            SET role = 'engineer',
                department_id = d.id
            FROM route_card.departments d
            JOIN route_card.sbus s ON s.id = d.sbu
            WHERE u.role = 'ied'
              AND d.code = 'IED'
              AND d.is_active = TRUE
              AND TRIM(COALESCE(u.sbu, '')) = TRIM(s.name);
            """
        )
        cursor.execute(
            """
            UPDATE route_card.users SET role = 'engineer' WHERE role = 'ied';
            """
        )
        # Assign remaining users (non-admin) without department to PMG of their SBU
        cursor.execute(
            """
            UPDATE route_card.users u
            SET department_id = d.id
            FROM route_card.departments d
            JOIN route_card.sbus s ON s.id = d.sbu
            WHERE u.department_id IS NULL
              AND u.role <> 'admin'
              AND d.code = 'PMG'
              AND d.is_active = TRUE
              AND TRIM(COALESCE(u.sbu, '')) = TRIM(s.name);
            """
        )
        print(
            "departments: ensured PMG/IED per SBU; users.department_id; "
            "migrated ied→engineer+IED dept"
        )

        # Session plant/SBU for admin analyze → Share-to-IED routing
        cursor.execute(
            """
            ALTER TABLE route_card.sessions
            ADD COLUMN IF NOT EXISTS plant VARCHAR(32) NOT NULL DEFAULT '';
            """
        )
        cursor.execute(
            """
            ALTER TABLE route_card.sessions
            ADD COLUMN IF NOT EXISTS sbu VARCHAR(128) NOT NULL DEFAULT '';
            """
        )
        # Backfill from latest analyze job plant when session.plant empty
        cursor.execute(
            """
            UPDATE route_card.sessions s
            SET plant = j.plant
            FROM (
                SELECT DISTINCT ON (session) session, plant
                FROM route_card.analyze_jobs
                WHERE TRIM(COALESCE(plant, '')) <> ''
                ORDER BY session, id DESC
            ) j
            WHERE s.id = j.session
              AND TRIM(COALESCE(s.plant, '')) = '';
            """
        )
        cursor.execute(
            """
            UPDATE route_card.sessions s
            SET sbu = sb.name
            FROM route_card.sbus sb
            WHERE TRIM(COALESCE(s.plant, '')) <> ''
              AND TRIM(COALESCE(s.sbu, '')) = ''
              AND TRIM(COALESCE(sb.plant_id, '')) = TRIM(s.plant)
              AND sb.is_active = TRUE;
            """
        )
        cursor.execute(
            """
            UPDATE route_card.sessions s
            SET sbu = u.sbu
            FROM route_card.users u
            WHERE s."user" = u.id
              AND TRIM(COALESCE(s.sbu, '')) = ''
              AND TRIM(COALESCE(u.sbu, '')) <> '';
            """
        )
        print("sessions: plant/sbu columns for Share-to-IED routing")
    finally:
        cursor.close()
        conn.close()
