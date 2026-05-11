"""Conversión robusta de strings de fecha a ``datetime``.

El notebook legacy maneja al menos tres formatos heterogéneos
(visibles en exports de ``Tareas.csv``, ``IncidentesStefanini.csv`` y
``GLPI.csv``):

- ``"3/5/2026 9:14:30 AM"``    — M/D/YYYY 12h con AM/PM
- ``"4/6/2026 17:00:03"``      — M/D/YYYY 24h
- ``"2026-03-05 09:14:30"``    — ISO 8601

Esta capa intenta cada formato en orden y combina los resultados
parciales. Usar formato explícito es 10–100× más rápido que el
inferring de :func:`pd.to_datetime`, además de evitar las
adivinanzas ambiguas (``2/5/2026`` puede ser febrero o mayo).

Las funciones son puras: reciben una :class:`pandas.Series` o
DataFrame y retornan una nueva sin mutar el input.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final, Literal

import pandas as pd

from prisma_gti.core import TransformerError, get_logger

logger = get_logger(__name__)


DEFAULT_DATE_FORMATS: Final[tuple[str, ...]] = (
    "%m/%d/%Y %I:%M:%S %p",  # 12h con AM/PM (Tareas.csv, IncidentesStefanini)
    "%m/%d/%Y %H:%M:%S",     # 24h (variantes de los mismos exports)
    "%Y-%m-%d %H:%M:%S",     # ISO 8601 (Discovery / Aranda)
    "%d/%m/%Y %H:%M:%S",     # DD/MM/YYYY (fallback)
)

ErrorMode = Literal["raise", "coerce", "warn"]


def parse_date_column(
    series: pd.Series,
    formats: Sequence[str] | None = None,
    errors: ErrorMode = "warn",
) -> pd.Series:
    """Convierte una Series de strings a ``datetime`` probando varios formatos.

    Estrategia
    ----------
    1. Intenta cada formato en orden con ``errors='coerce'`` (NaT si
       no parsea).
    2. Para cada fila aún ``NaT``, intenta el siguiente formato.
    3. Las filas que ningún formato resolvió quedan ``NaT``.

    Parámetros
    ----------
    series : pd.Series
        Columna de strings (o tipos compatibles) a convertir.
    formats : Sequence[str] | None
        Lista de formatos a probar. Si es ``None``, usa
        :data:`DEFAULT_DATE_FORMATS`.
    errors : {"raise", "coerce", "warn"}
        - ``"warn"`` (default): NaT permitido; emite WARNING con el
          conteo si quedan filas sin parsear.
        - ``"raise"``: levanta :class:`TransformerError` si alguna
          fila no parsea.
        - ``"coerce"``: NaT permitido, sin warning (silencioso).

    Retorna
    -------
    pd.Series
        Nueva Series con dtype datetime64.
    """
    fmts = tuple(formats) if formats is not None else DEFAULT_DATE_FORMATS

    # Empezar con NaT y resolver progresivamente. Mantener una sola
    # Series acumulada — no concatenar listas.
    result = pd.to_datetime(pd.Series([pd.NaT] * len(series), index=series.index))
    pending_mask = result.isna() & series.notna()

    for fmt in fmts:
        if not pending_mask.any():
            break
        attempt = pd.to_datetime(series[pending_mask], format=fmt, errors="coerce")
        # Escribir solo donde attempt no es NaT.
        hit_idx = attempt.dropna().index
        result.loc[hit_idx] = attempt.loc[hit_idx]
        pending_mask = result.isna() & series.notna()

    unresolved = int(pending_mask.sum())
    if unresolved:
        if errors == "raise":
            samples = series[pending_mask].head(5).tolist()
            raise TransformerError(
                f"parse_date_column: {unresolved} filas no parseables con "
                f"formatos {list(fmts)}. Muestras: {samples}"
            )
        if errors == "warn":
            logger.warning(
                "parse_date_column: {} filas no parseables con formatos {} "
                "(quedan NaT)",
                unresolved,
                list(fmts),
            )

    return result


def add_date_features(
    df: pd.DataFrame,
    date_column: str,
) -> pd.DataFrame:
    """Agrega columnas ``<col>_anio``, ``<col>_mes``, ``<col>_dia``.

    La columna fuente debe ser de tipo datetime. Si no lo es, se
    levanta :class:`TransformerError`. El DataFrame de entrada no se
    muta — se retorna una copia con las tres columnas nuevas.
    """
    if date_column not in df.columns:
        raise TransformerError(
            f"add_date_features: columna {date_column!r} no encontrada."
        )

    series = df[date_column]
    if not pd.api.types.is_datetime64_any_dtype(series):
        raise TransformerError(
            f"add_date_features: columna {date_column!r} debe ser datetime; "
            f"recibido dtype {series.dtype}. Aplicar parse_date_column antes."
        )

    out = df.copy()
    out[f"{date_column}_anio"] = series.dt.year
    out[f"{date_column}_mes"] = series.dt.month
    out[f"{date_column}_dia"] = series.dt.day
    return out
