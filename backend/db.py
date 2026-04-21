import os
from pathlib import Path

import mysql.connector
from mysql.connector import Error


def _cargar_env_local() -> None:
    """Carga variables desde .env si existe y aun no estan definidas."""
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key and key not in os.environ:
            os.environ[key] = value


def obtener_conexion():
    """Crea una conexion MySQL usando variables de entorno.

    Variables soportadas:
    - DB_HOST (default: localhost)
    - DB_PORT (default: 3306)
    - DB_USER (default: root)
    - DB_PASSWORD (default: root1234)
    - DB_NAME (default: dashboard_inversiones)
    """
    _cargar_env_local()

    host = os.getenv("DB_HOST", "localhost")
    port = int(os.getenv("DB_PORT", "3306"))
    user = os.getenv("DB_USER", "root")
    password = os.getenv("DB_PASSWORD")
    database = os.getenv("DB_NAME", "dashboard_inversiones")

    if password is None:
        raise RuntimeError(
            "Falta DB_PASSWORD. Define DB_PASSWORD en variables de entorno o en backend/.env"
        )

    try:
        return mysql.connector.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
        )
    except Error as exc:
        raise RuntimeError(
            "No se pudo conectar a MySQL. Revisa DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME "
            f"(host={host}, user={user}, db={database}). Error original: {exc}"
        ) from exc
