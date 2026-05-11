"""Normalización de strings: utilidades puras y reutilizables.

Convierte cualquier texto en una forma canónica ``unidecode → strip
→ lower`` que el resto del pipeline usa para comparaciones
case-insensitive (sobre todo en la capa identity/ y en la
aplicación del catálogo de servicios).

Todas las funciones de este módulo son **puras**:

- No mutan el DataFrame de entrada (operan sobre copias o devuelven
  nuevas Series).
- No tienen I/O ni estado.
- Son seguras para componer en pipelines.
"""

from __future__ import annotations

import pandas as pd
from unidecode import unidecode

# Bloque 42 del notebook legacy aplica fixes hardcoded de casing sobre
# la columna `responsable`. Son normalizaciones cosméticas (no
# decisiones funcionales), por eso viven aquí y NO en el YAML de
# manual_overrides. Si la lista crece, considerar moverla a un YAML
# dedicado de normalizaciones.
_RESPONSABLE_CASING_FIXES: dict[str, str] = {
    "CARLOS MANUEL RIVERA B.": "Carlos Manuel Rivera Barreto",
    "FERNANDO MARQUEZ": "Fernando Alberto Marquez Morales",
    "HAROLD ADOLFO MENDOZA AVENDANO": "Harold Adolfo Mendoza Avendaño",
    "YESID ALEJANDRO MARTINEZ NUNEZ": "Yesid Alejandro Martínez Nuñez",
}


def normalize_text(value: str | None) -> str:
    """Normaliza un string a forma canónica ``unidecode-strip-lower``.

    Parámetros
    ----------
    value : str | None
        Texto a normalizar. ``None`` o NaN se tratan como string
        vacío para que el resultado sea siempre ``str``.

    Retorna
    -------
    str
        Texto normalizado, posiblemente vacío.
    """
    if value is None:
        return ""
    text = str(value)
    if not text or text != text:  # NaN check (NaN != NaN)
        return ""
    return unidecode(text).strip().lower()


def normalize_column(series: pd.Series) -> pd.Series:
    """Aplica :func:`normalize_text` vectorizado sobre una columna.

    Es equivalente a ``series.map(normalize_text)`` pero formaliza la
    contraparte vectorizada y mantiene el ``dtype`` como ``object``.
    """
    return series.map(normalize_text)


def fix_responsable_casing(
    df: pd.DataFrame,
    column: str = "responsable",
) -> pd.DataFrame:
    """Aplica los 4 fixes de casing sobre la columna ``responsable``.

    Replica el bloque 42 del notebook legacy
    (``ProyectoFinal3.ipynb``), donde valores específicos en MAYÚSCULA
    sin tildes se reemplazan por sus formas canónicas con casing
    apropiado y tildes correctas.

    Parámetros
    ----------
    df : pd.DataFrame
        DataFrame a procesar. No se muta — se retorna una copia.
    column : str
        Nombre de la columna sobre la que aplicar los fixes. Si la
        columna no existe, se retorna el DataFrame sin cambios.

    Retorna
    -------
    pd.DataFrame
        Copia con la columna corregida (cuando aplica).
    """
    if column not in df.columns:
        return df.copy()
    out = df.copy()
    out[column] = out[column].replace(_RESPONSABLE_CASING_FIXES)
    return out
