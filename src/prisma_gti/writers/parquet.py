"""Escritura/lectura de Parquet para cachés intermedios del pipeline.

Validado en Fase 2 (script 07): Parquet es 185× más rápido en
escritura y 404× en lectura comparado con Excel; además ocupa 54%
menos espacio en disco. Es el formato recomendado para todos los
artefactos intermedios entre etapas del pipeline.

Estas funciones son puras: reciben un DataFrame + ruta, retornan
la ruta escrita (o el DataFrame leído). No tienen estado.
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

from prisma_gti.core import WriterError, get_logger

logger = get_logger(__name__)


def write_parquet(
    df: pd.DataFrame,
    path: Path,
    *,
    overwrite: bool = True,
) -> Path:
    """Escribe ``df`` a Parquet en ``path``. Crea el padre si no existe.

    Parámetros
    ----------
    df : pd.DataFrame
        DataFrame a persistir.
    path : Path
        Ruta destino. El directorio padre se crea si no existe.
    overwrite : bool
        Si ``False`` y el archivo ya existe, levanta :class:`WriterError`.

    Retorna
    -------
    Path
        La ruta escrita (igual a ``path``).

    Lanza
    -----
    WriterError
        Si falla la escritura o si ``overwrite=False`` y el archivo
        ya existe.
    """
    target = Path(path)

    if target.exists() and not overwrite:
        raise WriterError(
            f"parquet: archivo ya existe en {target} y overwrite=False."
        )

    target.parent.mkdir(parents=True, exist_ok=True)

    logger.info("parquet: escribiendo {} ({} filas)", target, len(df))
    start = time.perf_counter()
    try:
        df.to_parquet(target, engine="pyarrow", index=False)
    except (OSError, ValueError) as exc:
        raise WriterError(
            f"parquet: fallo escribiendo {target}: {exc}"
        ) from exc
    elapsed = time.perf_counter() - start
    logger.info(
        "parquet: {} escrito ({} filas, {:.2f}s)",
        target,
        len(df),
        elapsed,
    )
    return target


def read_parquet(path: Path) -> pd.DataFrame:
    """Lee un archivo Parquet a DataFrame.

    Parámetros
    ----------
    path : Path
        Ruta del archivo Parquet.

    Retorna
    -------
    pd.DataFrame

    Lanza
    -----
    WriterError
        Si el archivo no existe o si falla la lectura.
    """
    target = Path(path)
    if not target.is_file():
        raise WriterError(
            f"parquet: archivo no encontrado en {target}."
        )

    logger.info("parquet: leyendo {}", target)
    start = time.perf_counter()
    try:
        df = pd.read_parquet(target, engine="pyarrow")
    except (OSError, ValueError) as exc:
        raise WriterError(
            f"parquet: fallo leyendo {target}: {exc}"
        ) from exc
    elapsed = time.perf_counter() - start
    logger.info(
        "parquet: {} leído ({} filas, {:.2f}s)",
        target,
        len(df),
        elapsed,
    )
    return df
