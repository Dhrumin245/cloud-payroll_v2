from alembic import context
from sqlalchemy import engine_from_config, pool, text

from app.config import get_settings
from app.models import Base

config = context.config
# configparser treats '%' specially, so escape it
config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))
target_metadata = Base.metadata

# Several replicas may start at the same moment (Kubernetes), and each one migrates on start-up.
# Without a lock two of them race to create the same tables and one crashes. On PostgreSQL we
# take a session-level advisory lock so the migrations queue up; the later ones then find
# nothing left to do. (Any constant works as the key; it only has to be the same everywhere.)
MIGRATION_LOCK_KEY = 727_274


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        locked = connection.dialect.name == "postgresql"
        if locked:
            connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": MIGRATION_LOCK_KEY})
            connection.commit()  # ends the implicit transaction; the session-level lock stays held
        try:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
        finally:
            if locked:
                connection.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": MIGRATION_LOCK_KEY}
                )
                connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
