"""Carga y validación de credenciales desde variables de entorno.

Lee el archivo ``.env`` con ``python-dotenv`` y expone las credenciales
como dataclasses inmutables con tipos fuertes. Falla con
:class:`ConfigurationError` si alguna credencial obligatoria está vacía
o ausente.

El módulo no abre conexiones; solo prepara los objetos que los loaders
consumirán más adelante.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from prisma_gti.core.exceptions import ConfigurationError


@dataclass(frozen=True)
class SqlServerCredential:
    """Conexión a una base de datos SQL Server.

    Atributos
    ---------
    driver : str
        Driver ODBC (típicamente ``"ODBC Driver 17 for SQL Server"``).
    server : str
        Host o IP del servidor.
    database : str
        Nombre de la base de datos.
    user : str
        Usuario de la cuenta de servicio.
    password : str
        Contraseña (debe llegar no vacía).
    connection_timeout : int
        Segundos máximos para establecer la conexión.
    query_timeout : int
        Segundos máximos por consulta.
    """

    driver: str
    server: str
    database: str
    user: str
    password: str
    connection_timeout: int
    query_timeout: int


@dataclass(frozen=True)
class LdapCredential:
    """Configuración de la conexión LDAP / Active Directory.

    Atributos
    ---------
    server : str
        URL del servidor LDAP (ej. ``"ldap://172.16.0.5:389"``).
    base_dn : str
        DN base donde se realizan las búsquedas.
    user : str
        Cuenta de servicio (formato ``DOMINIO\\usuario``).
    password : str
        Contraseña de la cuenta de servicio.
    batch_size : int
        Tamaño de página para búsquedas batch con filtro OR.
    timeout : int
        Segundos máximos por operación LDAP.
    """

    server: str
    base_dn: str
    user: str
    password: str
    batch_size: int
    timeout: int


@dataclass(frozen=True)
class ExternalUrls:
    """URLs públicas consumidas por el pipeline de modelos."""

    indicadores_periodo_url: str
    indicadores_periodo_2026_url: str


@dataclass(frozen=True)
class Secrets:
    """Conjunto completo de credenciales y parámetros sensibles del proceso."""

    aranda_db: SqlServerCredential
    discovery_db: SqlServerCredential
    kactus_db: SqlServerCredential
    ldap: LdapCredential
    external_urls: ExternalUrls
    paths_overrides: dict[str, Path] = field(default_factory=dict)
    log_level: str = "INFO"
    log_file: Path = Path("./logs/prisma.log")
    debug: bool = False


def _require(env_var: str) -> str:
    """Devuelve la variable o levanta ConfigurationError si está vacía."""
    value = os.environ.get(env_var, "").strip()
    if not value:
        raise ConfigurationError(
            f"Variable de entorno requerida no definida o vacía: {env_var}. "
            "Revisa el archivo .env."
        )
    return value


def _optional(env_var: str, default: str = "") -> str:
    """Devuelve la variable o ``default`` si no está definida."""
    return os.environ.get(env_var, default).strip()


def _optional_path(env_var: str) -> Path | None:
    """Devuelve un :class:`Path` o ``None`` si la variable no está definida."""
    raw = os.environ.get(env_var, "").strip()
    return Path(raw) if raw else None


def _optional_int(env_var: str, default: int) -> int:
    """Devuelve la variable como entero, o ``default`` si está vacía."""
    raw = os.environ.get(env_var, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigurationError(
            f"Variable {env_var} debe ser entero, recibido: {raw!r}"
        ) from exc


def _optional_bool(env_var: str, default: bool = False) -> bool:
    """Interpreta '1', 'true', 'yes', 'on' (case-insensitive) como ``True``."""
    raw = os.environ.get(env_var, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _load_sql_credential(prefix: str) -> SqlServerCredential:
    """Construye un :class:`SqlServerCredential` desde variables prefijadas.

    Parámetros
    ----------
    prefix : str
        Prefijo de las variables de entorno (ej. ``"ARANDA_DB"``).
    """
    return SqlServerCredential(
        driver=_require(f"{prefix}_DRIVER"),
        server=_require(f"{prefix}_SERVER"),
        database=_require(f"{prefix}_NAME"),
        user=_require(f"{prefix}_USER"),
        password=_require(f"{prefix}_PASSWORD"),
        connection_timeout=_optional_int("DB_CONNECTION_TIMEOUT", 30),
        query_timeout=_optional_int("DB_QUERY_TIMEOUT", 300),
    )


def _load_ldap_credential() -> LdapCredential:
    """Construye un :class:`LdapCredential` desde las variables ``LDAP_*``."""
    return LdapCredential(
        server=_require("LDAP_SERVER"),
        base_dn=_require("LDAP_BASE_DN"),
        user=_require("LDAP_USER"),
        password=_require("LDAP_PASSWORD"),
        batch_size=_optional_int("LDAP_BATCH_SIZE", 200),
        timeout=_optional_int("LDAP_TIMEOUT", 10),
    )


def load_secrets(env_file: Path | None = None) -> Secrets:
    """Carga ``.env`` y devuelve un :class:`Secrets` validado.

    Parámetros
    ----------
    env_file : Path | None
        Ruta explícita al archivo ``.env``. Si es ``None`` se busca
        automáticamente en el cwd y en directorios superiores.

    Retorna
    -------
    Secrets
        Credenciales y parámetros sensibles validados.

    Lanza
    -----
    ConfigurationError
        Si alguna credencial requerida está vacía o ausente.
    """
    if env_file is not None:
        load_dotenv(env_file, override=False)
    else:
        load_dotenv(override=False)

    paths_overrides: dict[str, Path] = {}
    for env_var, key in [
        ("DATA_RAW_DIR", "raw_dir"),
        ("DATA_INTERIM_DIR", "interim_dir"),
        ("DATA_OUTPUT_DIR", "output_dir"),
    ]:
        path = _optional_path(env_var)
        if path is not None:
            paths_overrides[key] = path

    return Secrets(
        aranda_db=_load_sql_credential("ARANDA_DB"),
        discovery_db=_load_sql_credential("DISCOVERY_DB"),
        kactus_db=_load_sql_credential("KACTUS_DB"),
        ldap=_load_ldap_credential(),
        external_urls=ExternalUrls(
            indicadores_periodo_url=_require("INDICADORES_PERIODO_URL"),
            indicadores_periodo_2026_url=_require("INDICADORES_PERIODO_2026_URL"),
        ),
        paths_overrides=paths_overrides,
        log_level=_optional("LOG_LEVEL", "INFO") or "INFO",
        log_file=_optional_path("LOG_FILE") or Path("./logs/prisma.log"),
        debug=_optional_bool("DEBUG", False),
    )
