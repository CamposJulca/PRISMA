"""Loader de los tres Stored Procedures de ArandaDB8.

Ejecuta ``SP_INCIDENTESGTI1``, ``SP_SERVICECALL1`` y ``SP_CHANGES1``
sobre una única conexión pyodbc, en orden, con manejo de errores
diferenciado por SP. Los DataFrames se devuelven con el esquema
crudo de cada SP (sin renombrar columnas, sin transformar fechas,
sin filtros) — esa es responsabilidad de los transformers.

Sin filtros de fecha — la carga incremental fue descartada en
Fase 2 (ver docs/fase2_profiling.md §5.4).
"""

from __future__ import annotations

import time
import warnings
from dataclasses import dataclass
from typing import Final

import pandas as pd
import pyodbc

from prisma_gti.core import LoaderError, SqlServerCredential
from prisma_gti.loaders.base import BaseLoader

# pandas emite UserWarning recomendando SQLAlchemy cuando se usa
# read_sql con una conexión pyodbc directa. Mantenemos pyodbc directo
# por paridad con el notebook legacy y porque pyodbc nos da control
# fino sobre timeouts y connection strings. La migración a SQLAlchemy
# es candidato de roadmap, no de esta versión. NO eliminar este
# filterwarnings sin antes migrar a SQLAlchemy.
warnings.filterwarnings(
    "ignore",
    message="pandas only supports SQLAlchemy.*",
    category=UserWarning,
)


_SP_INCIDENTES: Final[str] = "exec SP_INCIDENTESGTI1"
_SP_REQUERIMIENTOS: Final[str] = "exec SP_SERVICECALL1"
_SP_CAMBIOS: Final[str] = "exec SP_CHANGES1"


@dataclass(frozen=True)
class ArandaSqlResult:
    """DataFrames crudos de los 3 SP de ArandaDB8.

    Atributos
    ---------
    incidentes : pd.DataFrame
        Resultado de ``SP_INCIDENTESGTI1``.
    requerimientos : pd.DataFrame
        Resultado de ``SP_SERVICECALL1``.
    cambios : pd.DataFrame
        Resultado de ``SP_CHANGES1``.
    """

    incidentes: pd.DataFrame
    requerimientos: pd.DataFrame
    cambios: pd.DataFrame


class ArandaSqlLoader(BaseLoader):
    """Carga los 3 SP de ArandaDB8 sobre una sola conexión pyodbc.

    Si cualquiera de los SP falla, se levanta :class:`LoaderError`
    cerrando la conexión limpiamente y sin retornar datos parciales.
    """

    def __init__(self, credentials: SqlServerCredential) -> None:
        super().__init__()
        self._credentials = credentials

    def load(self) -> ArandaSqlResult:
        """Conecta, ejecuta los 3 SP en orden y cierra la conexión.

        Retorna
        -------
        ArandaSqlResult
            DataFrames crudos de los 3 SP.

        Lanza
        -----
        LoaderError
            Si la conexión falla o si la ejecución de cualquier SP
            arroja error.
        """
        conn = self._open_connection()
        try:
            incidentes = self._run_sp(conn, _SP_INCIDENTES, "incidentes")
            requerimientos = self._run_sp(conn, _SP_REQUERIMIENTOS, "requerimientos")
            cambios = self._run_sp(conn, _SP_CAMBIOS, "cambios")
        finally:
            try:
                conn.close()
                self.logger.info("aranda_sql: conexión cerrada")
            except pyodbc.Error as exc:
                self.logger.warning(
                    "aranda_sql: error al cerrar conexión (ignorado): {}", exc
                )

        return ArandaSqlResult(
            incidentes=incidentes,
            requerimientos=requerimientos,
            cambios=cambios,
        )

    def _open_connection(self) -> pyodbc.Connection:
        """Abre la conexión pyodbc con timeouts del credential."""
        cred = self._credentials
        conn_str = (
            f"DRIVER={{{cred.driver}}};"
            f"SERVER={cred.server};"
            f"DATABASE={cred.database};"
            f"UID={cred.user};"
            f"PWD={cred.password}"
        )
        try:
            self.logger.info(
                "aranda_sql: conectando a {}/{} (timeout {}s)",
                cred.server,
                cred.database,
                cred.connection_timeout,
            )
            conn = pyodbc.connect(conn_str, timeout=cred.connection_timeout)
        except pyodbc.Error as exc:
            raise LoaderError(
                f"aranda_sql: no se pudo conectar a {cred.server}/{cred.database}: {exc}"
            ) from exc
        conn.timeout = cred.query_timeout
        return conn

    def _run_sp(
        self,
        conn: pyodbc.Connection,
        sp: str,
        label: str,
    ) -> pd.DataFrame:
        """Ejecuta un SP y devuelve su DataFrame crudo.

        Cualquier ``pyodbc.Error`` se re-lanza como :class:`LoaderError`
        con el label del SP para que el caller sepa cuál falló.
        Si el resultado tiene 0 filas se emite un WARNING — es
        trazabilidad operacional, no validación de datos.
        """
        self.logger.info("aranda_sql: ejecutando {} ({})", label, sp)
        start = time.perf_counter()
        try:
            df = pd.read_sql(sp, conn)
        except pyodbc.Error as exc:
            raise LoaderError(
                f"aranda_sql: SP {label!r} ({sp}) falló: {exc}"
            ) from exc
        elapsed = time.perf_counter() - start
        self.logger.info(
            "aranda_sql: {} → {} filas en {:.2f}s", label, len(df), elapsed
        )
        if len(df) == 0:
            self.logger.warning(
                "aranda_sql: SP {} retornó 0 filas, posible anomalía", label
            )
        return df
