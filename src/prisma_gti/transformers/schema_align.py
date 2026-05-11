"""Alineación de esquemas heterogéneos antes de concatenar DataFrames.

Las fuentes del pipeline producen DataFrames con esquemas distintos
(Discovery tiene una columna ``responsable`` directa, GEUS la deriva
de otra, ASMS agrega columnas extra para flujo Stefanini). Antes de
``pd.concat`` hay que llevarlas todas al mismo esquema canónico.

Esta capa no toma decisiones de negocio — solo alinea: agrega
columnas faltantes (con un ``fill_value``) y descarta columnas extra
(logueando WARNING con sus nombres para visibilidad operacional).

Funciones puras: los DataFrames retornados son nuevos, no modifican
los inputs.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pandas as pd

from prisma_gti.core import get_logger

logger = get_logger(__name__)


# Esquema canónico del consolidado ``indicators1.xlsx`` — derivado del
# rename map del bloque 152 de ``ProyectoFinal3.ipynb``. Las 14
# columnas son el contrato que las fuentes Discovery + Aranda + GLPI
# + GEUS + ASMS deben respetar antes del ``pd.concat`` del bloque 121
# / 180.
_INDICATORS1_SCHEMA: tuple[str, ...] = (
    "numero_caso",
    "tipo_de_caso",
    "usuariofinal",
    "responsable",
    "servicio",
    "fecha_creacion",
    "fecha_atencion",
    "fecha_solucion",
    "tiempoTranscurrido",
    "CUMPLE_ANS",
    "origen_caso",
    "proyecto",
    "username_resp",
    "username_ufinal",
)


def get_indicators1_schema() -> list[str]:
    """Retorna la lista canónica de columnas de ``indicators1.xlsx``.

    Son 14 columnas, en orden. La lista es un *snapshot* del rename
    map del notebook legacy (bloque 152 de ``ProyectoFinal3.ipynb``)
    y del esquema final que consume Power BI. Cualquier cambio aquí
    debe ir acompañado de una validación contra el output existente.
    """
    return list(_INDICATORS1_SCHEMA)


def align_schemas(
    dataframes: dict[str, pd.DataFrame],
    target_columns: Sequence[str],
    fill_value: Any = None,
) -> dict[str, pd.DataFrame]:
    """Alinea múltiples DataFrames al mismo esquema canónico.

    Para cada DataFrame del input:

    - Si le faltan columnas de ``target_columns``, las agrega con
      ``fill_value``.
    - Si tiene columnas extra (no listadas en ``target_columns``), las
      descarta. Se loguea WARNING con los nombres descartados.
    - Reordena para que las columnas queden en el orden de
      ``target_columns``.

    Parámetros
    ----------
    dataframes : dict[str, pd.DataFrame]
        DataFrames a alinear, keyed por nombre lógico (sirve para
        identificarlos en los logs).
    target_columns : Sequence[str]
        Esquema destino. Típicamente :func:`get_indicators1_schema`.
    fill_value : Any
        Valor con el que rellenar columnas faltantes. Default
        ``None`` (se traduce a ``NaN`` en pandas).

    Retorna
    -------
    dict[str, pd.DataFrame]
        DataFrames alineados, mismo orden de keys que el input.
    """
    target_list = list(target_columns)
    target_set = set(target_list)
    aligned: dict[str, pd.DataFrame] = {}

    for name, df in dataframes.items():
        present = set(df.columns)
        missing = [c for c in target_list if c not in present]
        extra = [c for c in df.columns if c not in target_set]

        out = df.copy()
        if extra:
            logger.warning(
                "schema_align[{}]: descartando {} columnas extra: {}",
                name,
                len(extra),
                extra,
            )
            out = out.drop(columns=extra)
        for col in missing:
            out[col] = fill_value
        # Reordenar al esquema canónico.
        out = out[target_list]
        aligned[name] = out

        logger.info(
            "schema_align[{}]: {} filas alineadas ({} agregadas, {} "
            "descartadas)",
            name,
            len(out),
            len(missing),
            len(extra),
        )

    return aligned
