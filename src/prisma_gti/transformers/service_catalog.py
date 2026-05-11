"""Carga y aplicación del catálogo de servicios.

Encapsula las 90 reglas de ``config/catalogo_servicios.yaml``
divididas en tres secciones:

- ``indicadores_overrides`` (74) — pipeline histórico, bloque 127 del
  notebook legacy.
- ``asms_overrides`` (15) — pipeline Stefanini/ASMS, bloque 179.
- ``proyecto_overrides`` (1) — caso especial donde el match es por
  ``servicio`` pero la asignación recae en la columna ``proyecto``.

Todas las funciones de aplicación son **puras**: reciben un
DataFrame, retornan uno nuevo (o copia), nunca mutan el input.

El match es **case-sensitive** contra el valor crudo del export, en
paridad con ``df['servicio'] == 'X'`` del legacy. La normalización
case-insensitive vive en otra capa (identity/transformers).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from prisma_gti.core import ConfigurationError, get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class ServiceCatalog:
    """Las 3 secciones del YAML como diccionarios listos para ``.replace()``.

    Atributos
    ---------
    indicadores_mapping : dict[str, str]
        ``servicio`` viejo → ``servicio`` canónico para el pipeline
        histórico (74 reglas).
    asms_mapping : dict[str, str]
        Análogo para los DataFrames de ASMS (15 reglas).
    proyecto_mapping : dict[str, str]
        ``match_servicio`` → valor canónico para la columna
        ``proyecto``. El match se hace contra ``servicio``; el efecto
        recae sobre ``proyecto``.
    """

    indicadores_mapping: dict[str, str]
    asms_mapping: dict[str, str]
    proyecto_mapping: dict[str, str]


def load_service_catalog(yaml_path: Path) -> ServiceCatalog:
    """Carga ``catalogo_servicios.yaml`` como :class:`ServiceCatalog`.

    Lanza
    -----
    ConfigurationError
        Si el archivo no existe, no parsea, o alguna sección tiene
        formato inesperado.
    """
    path = Path(yaml_path)
    if not path.is_file():
        raise ConfigurationError(
            f"catalogo_servicios.yaml no encontrado en {path}."
        )

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigurationError(
            f"catalogo_servicios.yaml inválido: {exc}"
        ) from exc

    if not isinstance(raw, dict):
        raise ConfigurationError(
            "catalogo_servicios.yaml debe ser un mapping en la raíz."
        )

    indicadores = _load_from_to_section(
        raw.get("indicadores_overrides") or [], "indicadores_overrides"
    )
    asms = _load_from_to_section(
        raw.get("asms_overrides") or [], "asms_overrides"
    )
    proyecto = _load_proyecto_section(raw.get("proyecto_overrides") or [])

    logger.info(
        "service_catalog: cargado YAML {} → {} indicadores, {} asms, "
        "{} proyecto",
        path,
        len(indicadores),
        len(asms),
        len(proyecto),
    )

    return ServiceCatalog(
        indicadores_mapping=indicadores,
        asms_mapping=asms,
        proyecto_mapping=proyecto,
    )


def apply_indicadores_overrides(
    df: pd.DataFrame,
    catalog: ServiceCatalog,
) -> pd.DataFrame:
    """Aplica las 74 reglas de ``indicadores_overrides`` sobre ``servicio``.

    Si la columna ``servicio`` no existe, se retorna el DataFrame
    sin cambios (con copia defensiva). Replica el bloque 127 del
    notebook legacy como un único ``replace`` vectorizado.
    """
    return _apply_servicio_mapping(df, catalog.indicadores_mapping)


def apply_asms_overrides(
    df: pd.DataFrame,
    catalog: ServiceCatalog,
) -> pd.DataFrame:
    """Aplica las 15 reglas de ``asms_overrides`` sobre ``servicio``.

    Replica el bloque 179 del notebook legacy.
    """
    return _apply_servicio_mapping(df, catalog.asms_mapping)


def apply_proyecto_overrides(
    df: pd.DataFrame,
    catalog: ServiceCatalog,
) -> pd.DataFrame:
    """Aplica ``proyecto_overrides`` — match por ``servicio``, set en ``proyecto``.

    Para cada fila donde ``df['servicio'] == match_servicio``, escribe
    el valor canónico en ``df['proyecto']`` (vectorizado vía ``map`` +
    ``loc``). Si falta alguna de las dos columnas, retorna el DataFrame
    sin cambios.
    """
    if (
        "servicio" not in df.columns
        or "proyecto" not in df.columns
        or not catalog.proyecto_mapping
    ):
        return df.copy()
    out = df.copy()
    mapped = out["servicio"].map(catalog.proyecto_mapping)
    out.loc[mapped.dropna().index, "proyecto"] = mapped.dropna()
    return out


def _apply_servicio_mapping(
    df: pd.DataFrame,
    mapping: dict[str, str],
) -> pd.DataFrame:
    """Helper común: ``replace`` vectorizado sobre la columna ``servicio``."""
    if "servicio" not in df.columns or not mapping:
        return df.copy()
    out = df.copy()
    out["servicio"] = out["servicio"].replace(mapping)
    return out


def _load_from_to_section(entries: Any, section: str) -> dict[str, str]:
    """Carga una sección ``[{from, to}, ...]`` como dict ``from → to``."""
    if not isinstance(entries, list):
        raise ConfigurationError(
            f"{section} debe ser una lista de mappings."
        )
    result: dict[str, str] = {}
    for idx, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            raise ConfigurationError(
                f"{section}[{idx}] debe ser un mapping."
            )
        try:
            origin = str(entry["from"])
            target = str(entry["to"])
        except KeyError as exc:
            raise ConfigurationError(
                f"{section}[{idx}] le falta clave {exc}."
            ) from exc
        result[origin] = target
    return result


def _load_proyecto_section(entries: Any) -> dict[str, str]:
    """Carga sección ``proyecto_overrides``.

    La forma del YAML es ``{match_servicio, proyecto}`` — diferente a
    las otras secciones porque el match y la asignación van a columnas
    distintas. El resultado es un dict ``match_servicio → proyecto``
    que el resolver consume vía ``.map()``.
    """
    if not isinstance(entries, list):
        raise ConfigurationError(
            "proyecto_overrides debe ser una lista de mappings."
        )
    result: dict[str, str] = {}
    for idx, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            raise ConfigurationError(
                f"proyecto_overrides[{idx}] debe ser un mapping."
            )
        try:
            match_servicio = str(entry["match_servicio"])
            proyecto = str(entry["proyecto"])
        except KeyError as exc:
            raise ConfigurationError(
                f"proyecto_overrides[{idx}] le falta clave {exc}."
            ) from exc
        result[match_servicio] = proyecto
    return result
