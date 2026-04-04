from logging.config import fileConfig
import os
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config
from sqlalchemy import pool

from papervisor.db.base import Base
from papervisor.db import models  # noqa: F401  (ensure models are registered)

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Allow overriding the DB URL from the environment (useful for Docker/future DB backends).
env_db_url = os.environ.get('PAPERVISOR_DATABASE_URL') or os.environ.get('DATABASE_URL')
if not env_db_url:
    db_path = os.environ.get('PAPERVISOR_DB_PATH')
    if db_path:
        p = Path(db_path).expanduser()
        env_db_url = f"sqlite:///{p.as_posix()}" if not p.is_absolute() else f"sqlite:////{p.as_posix().lstrip('/')}"
if env_db_url:
    config.set_main_option('sqlalchemy.url', env_db_url)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        if connection.dialect.name == 'sqlite':
            connection.exec_driver_sql('PRAGMA foreign_keys=ON')

        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
