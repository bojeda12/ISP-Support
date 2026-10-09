"""Carga local explícita: producción y variables del proceso tienen prioridad."""

import os

from dotenv import dotenv_values, load_dotenv


def load_development_env(base_dir):
    if os.getenv("DJANGO_ENV", "development") not in {"development", "test"}:
        return
    path = base_dir / ".env"
    if path.is_file() and dotenv_values(path, interpolate=False).get("DJANGO_ENV", "development") in {"development", "test"}:
        load_dotenv(path, override=False, interpolate=False)
