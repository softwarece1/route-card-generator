"""Pony ORM bind — route_card schema only."""

from pony.orm import Database, db_session

from app.config.settings import settings

db = Database()


def connect_to_db():
    db.bind(
        provider="postgres",
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        database=settings.DB_NAME,
    )

    with db_session:
        conn = db.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("CREATE SCHEMA IF NOT EXISTS route_card")
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise RuntimeError(f"Failed to create route_card schema: {e}") from e
        finally:
            cursor.close()

    from .migrations_route_card import run_migrations

    run_migrations()

    # Register entities before mapping
    from app.route_card import models as route_card_models  # noqa: F401

    db.generate_mapping(create_tables=True)

    # Idempotent demo catalog + dept_head/IED users (needs mapping)
    try:
        from app.route_card.work_centers import (
            seed_default_catalog,
            seed_dept_head_and_ied_users,
        )

        wc_res = seed_default_catalog()
        print(
            f"seeded work centres/machines: created={wc_res.get('created')} "
            f"machines={wc_res.get('machinesCreated')} depts={wc_res.get('deptCount')}"
        )
        user_res = seed_dept_head_and_ied_users()
        print(
            f"seeded dept_head/IED users: created={user_res.get('created')} "
            f"skipped={user_res.get('skipped')}"
        )
    except Exception as exc:
        print(f"warning: catalog/user seed skipped: {exc}")
