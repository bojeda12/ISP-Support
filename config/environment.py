"""Configuración de base de datos mediante variables de entorno."""

import os

from django.core.exceptions import ImproperlyConfigured


def database_config(base_dir):
    engine = os.getenv("DB_ENGINE", "sqlite")
    if engine == "sqlite":
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": base_dir / "db.sqlite3"}
    if engine == "postgresql":
        required = ("DB_NAME", "DB_USER", "DB_PASSWORD", "DB_HOST", "DB_PORT")
        missing = [name for name in required if not os.getenv(name)]
        if missing:
            raise ImproperlyConfigured(f"Missing database variables: {', '.join(missing)}")
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ["DB_NAME"],
            "USER": os.environ["DB_USER"],
            "PASSWORD": os.environ["DB_PASSWORD"],
            "HOST": os.environ["DB_HOST"],
            "PORT": os.environ["DB_PORT"],
        }
    raise ImproperlyConfigured("DB_ENGINE must be sqlite or postgresql")
