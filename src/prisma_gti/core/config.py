"""Configuración tipada cargada desde ``config/settings.yaml``.

Lee el YAML, valida estructura y tipos básicos, aplica overrides desde
:class:`Secrets` (rutas que vengan del ``.env``), y expone un
:class:`Settings` inmutable que el resto del pipeline consume.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from prisma_gti.core.exceptions import ConfigurationError
from prisma_gti.core.secrets import Secrets


_DEFAULT_SETTINGS_PATH = Path("config/settings.yaml")


@dataclass(frozen=True)
class Paths:
    """Rutas que el pipeline usa para leer y escribir artefactos."""

    raw_dir: Path
    interim_dir: Path
    output_dir: Path
    config_dir: Path
    log_dir: Path


@dataclass(frozen=True)
class BatchSizes:
    """Tamaños de batch para operaciones que se procesan en chunks."""

    ldap_batch: int


@dataclass(frozen=True)
class CutoffDates:
    """Fechas de corte referenciales.

    Estas fechas son metadata informativa y NO se usan como filtros
    activos en las consultas SQL en esta versión. La carga incremental
    fue descartada en Fase 2 (ver docs/fase2_profiling.md §5.4).
    """

    historical_start: date
    asms_start: date
    tareas_start: date


@dataclass(frozen=True)
class CatalogConfig:
    """Rutas a los catálogos editables por el equipo funcional."""

    catalogo_servicios_path: Path
    excepciones_usuarios_path: Path


@dataclass(frozen=True)
class Settings:
    """Configuración operacional completa de un pipeline run."""

    paths: Paths
    batch_sizes: BatchSizes
    cutoff_dates: CutoffDates
    catalogs: CatalogConfig
    debug: bool


def _require_key(data: dict[str, Any], key: str, context: str) -> Any:
    """Devuelve ``data[key]`` o levanta ConfigurationError con contexto."""
    if not isinstance(data, dict) or key not in data:
        raise ConfigurationError(
            f"settings.yaml: falta la clave '{key}' en {context}."
        )
    return data[key]


def _parse_date(value: Any, key: str) -> date:
    """Convierte un valor del YAML a :class:`date`."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ConfigurationError(
                f"settings.yaml: '{key}' no es una fecha ISO válida: {value!r}"
            ) from exc
    raise ConfigurationError(
        f"settings.yaml: '{key}' debe ser una fecha (YYYY-MM-DD), "
        f"recibido tipo {type(value).__name__}."
    )


def load_settings(
    yaml_path: Path | None = None,
    secrets: Secrets | None = None,
) -> Settings:
    """Carga ``settings.yaml`` y retorna un :class:`Settings` validado.

    Parámetros
    ----------
    yaml_path : Path | None
        Ruta al archivo YAML. Si es ``None`` usa
        ``config/settings.yaml`` relativo al cwd.
    secrets : Secrets | None
        Si se provee, ``secrets.paths_overrides`` reemplaza las rutas
        equivalentes del YAML, y ``secrets.debug`` reemplaza la bandera
        ``debug`` del YAML.

    Retorna
    -------
    Settings
        Configuración inmutable lista para inyectar en el pipeline.

    Lanza
    -----
    ConfigurationError
        Si el archivo no existe, no parsea o le falta una clave.
    """
    path = yaml_path if yaml_path is not None else _DEFAULT_SETTINGS_PATH
    if not path.is_file():
        raise ConfigurationError(f"settings.yaml no encontrado en {path}.")

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"settings.yaml inválido: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigurationError("settings.yaml debe ser un mapping en la raíz.")

    paths_data = _require_key(raw, "paths", "raíz")
    batch_data = _require_key(raw, "batch_sizes", "raíz")
    dates_data = _require_key(raw, "cutoff_dates", "raíz")
    catalogs_data = _require_key(raw, "catalogs", "raíz")

    paths = Paths(
        raw_dir=Path(_require_key(paths_data, "raw_dir", "paths")),
        interim_dir=Path(_require_key(paths_data, "interim_dir", "paths")),
        output_dir=Path(_require_key(paths_data, "output_dir", "paths")),
        config_dir=Path(_require_key(paths_data, "config_dir", "paths")),
        log_dir=Path(_require_key(paths_data, "log_dir", "paths")),
    )

    if secrets is not None and secrets.paths_overrides:
        overrides = secrets.paths_overrides
        paths = replace(
            paths,
            raw_dir=overrides.get("raw_dir", paths.raw_dir),
            interim_dir=overrides.get("interim_dir", paths.interim_dir),
            output_dir=overrides.get("output_dir", paths.output_dir),
        )

    batch_sizes = BatchSizes(
        ldap_batch=int(_require_key(batch_data, "ldap_batch", "batch_sizes")),
    )

    cutoff_dates = CutoffDates(
        historical_start=_parse_date(
            _require_key(dates_data, "historical_start", "cutoff_dates"),
            "cutoff_dates.historical_start",
        ),
        asms_start=_parse_date(
            _require_key(dates_data, "asms_start", "cutoff_dates"),
            "cutoff_dates.asms_start",
        ),
        tareas_start=_parse_date(
            _require_key(dates_data, "tareas_start", "cutoff_dates"),
            "cutoff_dates.tareas_start",
        ),
    )

    catalogs = CatalogConfig(
        catalogo_servicios_path=Path(
            _require_key(catalogs_data, "catalogo_servicios", "catalogs")
        ),
        excepciones_usuarios_path=Path(
            _require_key(catalogs_data, "excepciones_usuarios", "catalogs")
        ),
    )

    debug = bool(secrets.debug) if secrets is not None else bool(raw.get("debug", False))

    return Settings(
        paths=paths,
        batch_sizes=batch_sizes,
        cutoff_dates=cutoff_dates,
        catalogs=catalogs,
        debug=debug,
    )
