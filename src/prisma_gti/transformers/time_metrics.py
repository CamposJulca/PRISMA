"""Cálculo de métricas de tiempo y ANS (Acuerdo de Nivel de Servicio).

Estas son las funciones más críticas funcionalmente del pipeline: el
output de ``indicators1.xlsx`` que consume Power BI depende
directamente de ``tiempoTranscurrido`` y ``CUMPLE_ANS``.

Decisiones de diseño
--------------------

- **Tiempo en MINUTOS**. Los bloques 103, 130 y 162 del legacy
  dividen explícitamente ``dt.total_seconds() / 60``.
- **NaT/NaN propagan a NaN** en :func:`compute_tiempo_transcurrido`
  y :func:`compute_tiempo_atencion` (comportamiento natural de
  pandas con datetime).
- **CUMPLE_ANS_ATENCION** sigue la lógica del bloque 24 de
  ``Indicadores2026.ipynb``: ``np.where(tiempo > 0, 'SI', 'NO')``.
  Esto **mapea NaN → 'NO'** silenciosamente — comportamiento
  intencional para paridad con el notebook legacy (las fechas
  faltantes se cuentan como 'no cumplió').
- **GEUS tiempo fijo = 300**. Es decisión de negocio validada por
  Fabián (bloque 105), no un bug. La fuente legacy GEUS está fuera
  de soporte desde marzo 2025 y se le asigna un valor constante en
  lugar de calcular. Pareja con :func:`set_cumple_ans_geus`
  (hardcode ``'SI'``, bloque 102).
- **CUMPLE_ANS** *no se calcula* desde tiempo + umbral. La columna
  viene del export en la mayoría de fuentes; solo se **normaliza**
  (``'Cumple'`` → ``'SI'``, ``'No cumple'`` → ``'NO'``, opcionalmente
  invertir SI↔NO para GLPI). Ver :func:`normalize_cumple_ans`.
- **Tareas**: la columna CUMPLE_ANS se deriva del signo de
  ``TIEMPO REAL TAREA`` (bloque 163). Ver
  :func:`compute_cumple_ans_tareas`.
- **GLPI tiempos en texto**: la columna ``TIEMPO_SOLUCION.1`` viene
  como ``"5 horas 30 minutos"``; :func:`parse_glpi_duration_string`
  la convierte a minutos enteros vectorizadamente (bloque 64).

Todas las funciones son puras: reciben un DataFrame, retornan una
copia. Sin ``iterrows``, sin ``apply`` innecesario.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from prisma_gti.core import TransformerError, get_logger

logger = get_logger(__name__)

GEUS_FIXED_TIME_MINUTES: int = 300


def compute_tiempo_transcurrido(
    df: pd.DataFrame,
    fecha_inicio_col: str,
    fecha_fin_col: str,
    result_col: str = "tiempoTranscurrido",
) -> pd.DataFrame:
    """Calcula ``(fecha_fin - fecha_inicio)`` en **minutos**.

    Replica el patrón de los bloques 103, 130 y 162 del notebook
    legacy. Ambas columnas deben ser datetime; si alguna es ``NaT``,
    el resultado para esa fila es ``NaN``.

    Parámetros
    ----------
    df : pd.DataFrame
        DataFrame con las dos columnas de fecha. No se muta — se
        retorna una copia.
    fecha_inicio_col : str
        Columna con la fecha de inicio (típicamente ``fecha_creacion``
        o ``fecha_atencion``).
    fecha_fin_col : str
        Columna con la fecha final (típicamente ``fecha_solucion``).
    result_col : str
        Nombre de la columna a crear/sobreescribir con el resultado.

    Retorna
    -------
    pd.DataFrame
        Copia con la nueva columna en minutos (``float64`` con
        posibles ``NaN``).
    """
    _check_datetime_columns(df, (fecha_inicio_col, fecha_fin_col))
    out = df.copy()
    delta = out[fecha_fin_col] - out[fecha_inicio_col]
    out[result_col] = delta.dt.total_seconds() / 60.0
    return out


def compute_tiempo_atencion(
    df: pd.DataFrame,
    fecha_estimada_atencion_col: str,
    fecha_atencion_col: str,
    result_col: str = "tiempoTranscurridoAtencion",
) -> pd.DataFrame:
    """Calcula ``(estimada - atencion)`` en **minutos**.

    Replica el bloque 23 de ``Indicadores2026.ipynb``: la métrica
    mide el *slack hasta el SLA de atención*. Si la atención fue
    antes de la estimada, el slack es positivo (la regla
    :func:`compute_cumple_ans_atencion` lo clasifica como ``'SI'``).
    Si la atención fue después, el slack es negativo (``'NO'``).

    NaT → NaN propagan naturalmente.
    """
    _check_datetime_columns(
        df, (fecha_estimada_atencion_col, fecha_atencion_col)
    )
    out = df.copy()
    delta = out[fecha_estimada_atencion_col] - out[fecha_atencion_col]
    out[result_col] = delta.dt.total_seconds() / 60.0
    return out


def normalize_cumple_ans(
    df: pd.DataFrame,
    column: str = "CUMPLE_ANS",
    invert: bool = False,
) -> pd.DataFrame:
    """Normaliza los valores de la columna ``CUMPLE_ANS`` a ``'SI'``/``'NO'``.

    Combina dos transformaciones del notebook legacy:

    - Bloque 181 (consolidación final): ``'Cumple'`` → ``'SI'``,
      ``'No cumple'`` → ``'NO'``.
    - Bloque 55 (GLPI): invierte ``'SI'`` ↔ ``'NO'`` para corregir
      la paradoja del export — la fuente reporta cumplimiento como
      "tiempo excedido", semánticamente invertido respecto a las
      otras fuentes.

    Parámetros
    ----------
    df : pd.DataFrame
        DataFrame con la columna a normalizar. No se muta — se
        retorna una copia.
    column : str
        Nombre de la columna (default ``'CUMPLE_ANS'``).
    invert : bool
        Si ``True``, además invierte ``'SI'`` ↔ ``'NO'`` (paridad
        con el fix de GLPI del bloque 55).

    Retorna
    -------
    pd.DataFrame
        Copia con la columna normalizada. Valores fuera de los
        mapeos conocidos quedan intactos.
    """
    if column not in df.columns:
        return df.copy()

    out = df.copy()
    canonical_map = {"Cumple": "SI", "No cumple": "NO"}
    out[column] = out[column].replace(canonical_map)

    if invert:
        # Aplicar la inversión en dos pasos vía valores intermedios para
        # no mapear de vuelta en una segunda pasada.
        inversion_map = {"SI": "__TMP_NO__", "NO": "__TMP_SI__"}
        out[column] = out[column].replace(inversion_map)
        finalize_map = {"__TMP_NO__": "NO", "__TMP_SI__": "SI"}
        out[column] = out[column].replace(finalize_map)

    return out


def compute_cumple_ans_atencion(
    df: pd.DataFrame,
    tiempo_col: str = "tiempoTranscurridoAtencion",
    result_col: str = "CUMPLE_ANS_ATENCION",
) -> pd.DataFrame:
    """Calcula ``CUMPLE_ANS_ATENCION = 'SI' si tiempo > 0 else 'NO'``.

    Replica literalmente el bloque 24 de ``Indicadores2026.ipynb``::

        df['CUMPLE_ANS_ATENCION'] = np.where(df['tiempoTranscurridoAtencion'] > 0, 'SI', 'NO')

    **Importante:** ``np.where`` evalúa ``NaN > 0`` como ``False``,
    de modo que las filas con tiempo faltante quedan como ``'NO'``.
    Es comportamiento intencional, validado en sesión 6, para paridad
    estricta con el notebook legacy.
    """
    if tiempo_col not in df.columns:
        raise TransformerError(
            f"compute_cumple_ans_atencion: columna {tiempo_col!r} no "
            f"encontrada."
        )
    out = df.copy()
    out[result_col] = np.where(out[tiempo_col] > 0, "SI", "NO")
    return out


def apply_geus_fixed_time(
    df: pd.DataFrame,
    value: int = GEUS_FIXED_TIME_MINUTES,
    result_col: str = "tiempoTranscurrido",
) -> pd.DataFrame:
    """Asigna tiempo fijo a registros de GEUS (decisión de negocio).

    Replica el bloque 105 del notebook legacy::

        geus['tiempoTranscurrido'] = '300'  # luego cast a int

    Esto NO es un bug. La fuente legacy GEUS está fuera de soporte
    desde marzo 2025 y la decisión funcional (validada por Fabián)
    fue asignar un valor constante en lugar de calcular tiempos
    reales sobre datos cuya calidad ya no se sostiene.

    Parámetros
    ----------
    df : pd.DataFrame
        DataFrame de registros de GEUS. No se muta — se retorna copia.
    value : int
        Minutos fijos a asignar. Default ``300`` (5 horas), como el
        legacy.
    result_col : str
        Columna a sobrescribir. Default ``'tiempoTranscurrido'``.
    """
    out = df.copy()
    out[result_col] = value
    return out


def set_cumple_ans_geus(
    df: pd.DataFrame,
    result_col: str = "CUMPLE_ANS",
    value: str = "SI",
) -> pd.DataFrame:
    """Asigna ``CUMPLE_ANS = 'SI'`` a todos los registros de GEUS.

    Replica el bloque 102 del notebook legacy::

        geus['CUMPLE_ANS'] = 'SI'

    Decisión de negocio validada por Fabián: GEUS está fuera de
    soporte desde marzo 2025 y se asume cumplimiento total para
    todos sus registros históricos. Pareja con
    :func:`apply_geus_fixed_time`.
    """
    out = df.copy()
    out[result_col] = value
    return out


def compute_cumple_ans_tareas(
    df: pd.DataFrame,
    tiempo_real_col: str = "TIEMPO REAL TAREA",
    result_col: str = "CUMPLE_ANS",
) -> pd.DataFrame:
    """Calcula ``CUMPLE_ANS`` para Tareas según signo de ``TIEMPO REAL``.

    Replica el bloque 163 del notebook legacy::

        tareas['CUMPLE_ANS'] = np.where(tareas['TIEMPO REAL TAREA'] < 0, 'SI', 'NO')

    Semántica del export: ``TIEMPO REAL TAREA`` es negativo cuando la
    tarea se completó antes del tiempo estimado en Aranda (cumplió
    ANS) y positivo cuando lo excedió. ``np.where`` evalúa
    ``NaN < 0`` como ``False`` → ``'NO'``; comportamiento intencional
    para paridad con el legacy.
    """
    if tiempo_real_col not in df.columns:
        raise TransformerError(
            f"compute_cumple_ans_tareas: columna {tiempo_real_col!r} "
            f"no encontrada."
        )
    out = df.copy()
    out[result_col] = np.where(out[tiempo_real_col] < 0, "SI", "NO")
    return out


_GLPI_HORAS_PATTERN = r"(\d+)\s*horas?"
_GLPI_MINUTOS_PATTERN = r"(\d+)\s*(?:minutos?|min)"


def parse_glpi_duration_string(series: pd.Series) -> pd.Series:
    """Convierte strings tipo ``"5 horas 30 minutos"`` a minutos enteros.

    Replica la función ``convertir_a_minutos`` del bloque 64 del
    notebook legacy, pero **vectorizado** con
    :meth:`pandas.Series.str.extract` (sin ``apply``).

    Reglas
    ------
    - Extrae horas con regex ``(\\d+)\\s*horas?`` (case-insensitive).
    - Extrae minutos con regex ``(\\d+)\\s*(?:minutos?|min)``.
    - Componentes ausentes se tratan como 0.
    - Total = horas × 60 + minutos.

    Parámetros
    ----------
    series : pd.Series
        Columna de strings (típicamente ``GLPI.csv`` ``TIEMPO_SOLUCION``).
        Valores ``NaN`` retornan ``NaN``.

    Retorna
    -------
    pd.Series
        Series numérica (``float64``) con duración en minutos.
    """
    texts = series.astype(str)

    horas = (
        texts.str.extract(_GLPI_HORAS_PATTERN, flags=2)[0]  # re.IGNORECASE = 2
        .astype("Float64")
        .fillna(0)
    )
    minutos = (
        texts.str.extract(_GLPI_MINUTOS_PATTERN, flags=2)[0]
        .astype("Float64")
        .fillna(0)
    )

    total = horas * 60 + minutos
    # Preservar NaN del input original.
    result = total.astype("float64")
    result[series.isna()] = float("nan")
    return result


def _check_datetime_columns(
    df: pd.DataFrame,
    columns: tuple[str, ...],
) -> None:
    """Valida que las columnas existan y sean de tipo datetime."""
    for col in columns:
        if col not in df.columns:
            raise TransformerError(
                f"time_metrics: columna {col!r} no encontrada en el DataFrame."
            )
        if not pd.api.types.is_datetime64_any_dtype(df[col]):
            raise TransformerError(
                f"time_metrics: columna {col!r} debe ser datetime; "
                f"recibido dtype {df[col].dtype}. Aplicar parse_date_column "
                f"antes."
            )
