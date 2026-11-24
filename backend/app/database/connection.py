"""Pony ORM bind — route_card schema only."""

from pony.orm import Database, db_session

from app.config.settings import settings

db = Database()


_db_ready = False


def connect_to_db():
    global _db_ready
    if _db_ready and db.provider is not None:
        return

    if db.provider is None:
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

    try:
        db.generate_mapping(create_tables=True)
    except Exception as exc:
        msg = str(exc).lower()
        if "already" not in msg and "mapping" not in msg:
            raise
    _db_ready = True

    # Idempotent plant WC import + sbu_head/IED users (needs mapping)
    try:
        from app.route_card.work_centers import (
            deactivate_dummy_work_centers,
            import_work_centres_from_csv,
            seed_sbu_head_and_ied_users,
        )

        dummy_res = deactivate_dummy_work_centers()
        print(
            f"deactivated dummy work centres: wc={dummy_res.get('deactivated')} "
            f"machines={dummy_res.get('machinesDeactivated')}"
        )
        wc_res = import_work_centres_from_csv()
        print(
            f"imported work centres from CSV: created={wc_res.get('created')} "
            f"updated={wc_res.get('updated')} skipped={wc_res.get('skipped')}"
        )
        user_res = seed_sbu_head_and_ied_users()
        print(
            f"seeded sbu_head/IED users: created={user_res.get('created')} "
            f"skipped={user_res.get('skipped')} "
            f"reset={user_res.get('reset')}"
        )
    except Exception as exc:
        print(f"warning: catalog/user seed skipped: {exc}")
