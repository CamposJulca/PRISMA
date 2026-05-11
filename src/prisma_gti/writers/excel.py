"""Escritura de archivos Excel que consume Power BI.

Solo los 3 archivos finales del pipeline son ``.xlsx``
(``indicators1.xlsx``, ``provisionalASMS.xlsx``, ``tareas1.xlsx``).
Los artefactos intermedios usan Parquet por la diferencia de
rendimiento validada en Fase 2 (185× más rápido en escritura).

Esta capa NO aplica formato condicional, estilos, ni autofilters —
eso es responsabilidad de Power BI aguas abajo.
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

from prisma_gti.core import WriterError, get_logger

logger = get_logger(__name__)


def write_excel(
    df: pd.DataFrame,
    path: Path,
    *,
    sheet_name: str = "Sheet1",
    schema: list[str] | None = None,
    overwrite: bool = True,
) -> Path:
    """Escribe ``df`` a ``.xlsx`` usando openpyxl.

    Parámetros
    ----------
    df : pd.DataFrame
        DataFrame a persistir. El índice nunca se escribe
        (``index=False``).
    path : Path
        Ruta destino. El directorio padre se crea si no existe.
    sheet_name : str
        Nombre de la hoja en el archivo.
    schema : list[str] | None
        Si se provee:

        - Valida que ``df`` contenga **exactamente** ese conjunto de
          columnas (ni más ni menos).
        - Reordena ``df`` a ese orden antes de escribir.
        - Levanta :class:`WriterError` si faltan columnas o si
          aparecen columnas no listadas.
    overwrite : bool
        Si ``False`` y el archivo ya existe, levanta
        :class:`WriterError`.

    Retorna
    -------
    Path
        La ruta escrita.

    Lanza
    -----
    WriterError
        Si la escritura falla, si el esquema no se cumple, o si
        ``overwrite=False`` y el archivo ya existe.
    """
    target = Path(path)

    if target.exists() and not overwrite:
        raise WriterError(
            f"excel: archivo ya existe en {target} y overwrite=False."
        )

    if schema is not None:
        present = set(df.columns)
        target_set = set(schema)
        missing = target_set - present
        extra = present - target_set
        if missing or extra:
            raise WriterError(
                f"excel: el DataFrame no cumple el schema esperado en "
                f"{target}. Faltantes: {sorted(missing)}. "
                f"Extras: {sorted(extra)}."
            )
        df = df[schema]

    target.parent.mkdir(parents=True, exist_ok=True)

    logger.info("excel: escribiendo {} ({} filas)", target, len(df))
    start = time.perf_counter()
    try:
        df.to_excel(target, sheet_name=sheet_name, index=False, engine="openpyxl")
    except (OSError, ValueError) as exc:
        raise WriterError(
            f"excel: fallo escribiendo {target}: {exc}"
        ) from exc
    elapsed = time.perf_counter() - start
    logger.info(
        "excel: {} escrito ({} filas, {:.2f}s)",
        target,
        len(df),
        elapsed,
    )
    return target
