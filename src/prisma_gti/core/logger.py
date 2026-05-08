"""Configuración del logger basada en loguru.

Expone dos funciones públicas:

- :func:`configure_logging` — configura los sinks (stderr + archivo
  rotado) consumiendo opcionalmente un YAML con overrides.
- :func:`get_logger` — wrapper delgado que devuelve un logger asociado
  a un nombre de módulo, listo para usar en cualquier parte del pipeline.

Política de rotación: archivo nuevo cada día, retención 30 días,
compresión zip al rotar. Cumple el requisito de trazabilidad sin
saturar disco.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml
from loguru import logger as _logger

from prisma_gti.core.exceptions import ConfigurationError


_DEFAULT_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{extra[module]}</cyan> | "
    "<level>{message}</level>"
)


def configure_logging(
    config_path: Path | None,
    level: str = "INFO",
    log_file: Path | None = None,
) -> None:
    """Configura los sinks de loguru.

    Parámetros
    ----------
    config_path : Path | None
        Ruta a ``config/logging.yaml``. Si es ``None`` o el archivo no
        existe se aplican los defaults.
    level : str
        Nivel mínimo global (``"DEBUG"``, ``"INFO"``, ``"WARNING"``...).
        Puede sobrescribirse desde el YAML.
    log_file : Path | None
        Archivo destino del sink de archivo. Si es ``None`` solo se
        emite a stderr.

    Lanza
    -----
    ConfigurationError
        Si el YAML existe pero está corrupto.
    """
    overrides = _load_yaml_config(config_path) if config_path is not None else {}

    fmt = str(overrides.get("format", _DEFAULT_FORMAT))
    effective_level = str(overrides.get("level", level))
    rotation = str(overrides.get("rotation", "1 day"))
    retention = str(overrides.get("retention", "30 days"))
    compression = str(overrides.get("compression", "zip"))
    enqueue = bool(overrides.get("enqueue", True))

    _logger.remove()
    _logger.configure(extra={"module": "prisma_gti"})

    _logger.add(
        sys.stderr,
        level=effective_level,
        format=fmt,
        enqueue=enqueue,
        backtrace=False,
        diagnose=False,
    )

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        _logger.add(
            str(log_file),
            level=effective_level,
            format=fmt,
            rotation=rotation,
            retention=retention,
            compression=compression,
            enqueue=enqueue,
            backtrace=True,
            diagnose=False,
            encoding="utf-8",
        )


def get_logger(name: str) -> Any:
    """Devuelve un logger asociado al módulo ``name``.

    Parámetros
    ----------
    name : str
        Nombre lógico del módulo (típicamente ``__name__``).

    Retorna
    -------
    loguru.Logger
        Logger con el campo ``module`` ya bindeado.
    """
    return _logger.bind(module=name)


def _load_yaml_config(path: Path) -> dict[str, Any]:
    """Carga el YAML de logging o devuelve dict vacío si no existe."""
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"logging.yaml inválido: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigurationError("logging.yaml debe ser un mapping en la raíz.")
    return data
