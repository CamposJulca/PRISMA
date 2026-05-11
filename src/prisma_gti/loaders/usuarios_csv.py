"""Loader del CSV ``usuarios.csv`` (diccionario auxiliar de usuarios finales).

Archivo plano de 2 columnas (``username_ufinal``, ``usuariofinal``)
mantenido manualmente por el equipo funcional. Sirve como tercer
nivel de resolución de identidades en el pipeline histórico
(complementa Kactus + LDAP + manual_overrides):

- **Forward** (``username_ufinal`` → ``usuariofinal``) — usado por
  Discovery (bloque 48 del notebook legacy) para completar el
  nombre de display cuando el username está presente.
- **Inverse** (``usuariofinal`` → ``username_ufinal``) — usado por
  GLPI/GEUS/consolidado (bloques 93, 111, 135) cuando hay nombre
  pero no username.

Ambas direcciones se construyen en :mod:`prisma_gti.pipelines.historico`
a partir del DataFrame que retorna este loader.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Final

import pandas as pd

from prisma_gti.core import LoaderError
from prisma_gti.loaders.base import BaseLoader

_FILENAME: Final[str] = "usuarios.csv"

_FINGERPRINT_COLUMNS: Final[tuple[str, ...]] = (
    "username_ufinal",
    "usuariofinal",
)


class UsuariosCsvLoader(BaseLoader):
    """Carga ``usuarios.csv`` desde ``raw_dir``."""

    def __init__(self, raw_dir: Path) -> None:
        super().__init__()
        self._path = Path(raw_dir) / _FILENAME

    def load(self) -> pd.DataFrame:
        """Lee el CSV y valida sus columnas-huella.

        Retorna
        -------
        pd.DataFrame
            DataFrame con columnas ``username_ufinal`` y
            ``usuariofinal``.

        Lanza
        -----
        LoaderError
            Si el archivo no existe, si la lectura falla, o si faltan
            las columnas-huella.
        """
        if not self._path.exists():
            raise LoaderError(
                f"usuarios_csv: archivo no encontrado en {self._path}. "
                f"Verifica DATA_RAW_DIR y que usuarios.csv esté allí."
            )

        self.logger.info("usuarios_csv: leyendo {}", self._path)
        start = time.perf_counter()
        try:
            df = pd.read_csv(self._path, encoding="utf-8")
        except (OSError, ValueError, pd.errors.ParserError) as exc:
            raise LoaderError(
                f"usuarios_csv: fallo leyendo {self._path}: {exc}"
            ) from exc
        elapsed = time.perf_counter() - start
        self.logger.info(
            "usuarios_csv: {} → {} filas en {:.2f}s",
            _FILENAME,
            len(df),
            elapsed,
        )
        self._validate_schema(df, _FINGERPRINT_COLUMNS, source="usuarios_csv")
        return df
