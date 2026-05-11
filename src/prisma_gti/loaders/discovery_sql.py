"""Loader del Stored Procedure ``SP_CASOS_DISCOVERYGTI_V1`` de DiscovSQL.

Ejecuta el SP sobre una única conexión pyodbc y devuelve el DataFrame
con el esquema crudo, sin renombrar columnas ni convertir tipos —
esa es responsabilidad de los transformers.

Sin filtros de fecha — la carga incremental fue descartada en
Fase 2 (ver docs/fase2_profiling.md §5.4).
"""

from __future__ import annotations

import time
import warnings
from typing import Final

import pandas as pd
import pyodbc

from prisma_gti.core import LoaderError, SqlServerCredential
from prisma_gti.loaders.base import BaseLoader

# pandas emite UserWarning recomendando SQLAlchemy cuando se usa
# read_sql con una conexión pyodbc directa. Misma justificación que
# en aranda_sql.py (paridad con notebook legacy + control fino de
# timeouts). NO eliminar sin antes migrar a SQLAlchemy.
warnings.filterwarnings(
    "ignore",
    message="pandas only supports SQLAlchemy.*",
    category=UserWarning,
)


_SP_DISCOVERY: Final[str] = "exec SP_CASOS_DISCOVERYGTI_V1"


class DiscoverySqlLoader(BaseLoader):
    """Carga ``SP_CASOS_DISCOVERYGTI_V1`` de DiscovSQL.

    El SP devuelve un único resultado tabular con el histórico de
    casos del sistema Discovery. Cualquier fallo de conexión o de
    ejecución del SP se traduce a :class:`LoaderError` cerrando la
    conexión limpiamente.
    """

    def __init__(self, credentials: SqlServerCredential) -> None:
        super().__init__()
        self._credentials = credentials

    def load(self) -> pd.DataFrame:
        """Conecta, ejecuta el SP y cierra la conexión.

        Retorna
        -------
        pd.DataFrame
            Resultado crudo del SP, con el esquema entregado por
            DiscovSQL.

        Lanza
        -----
        LoaderError
            Si la conexión falla o si la ejecución del SP arroja
            error.
        """
        conn = self._open_connection()
        try:
            df = self._run_sp(conn)
        finally:
            try:
                conn.close()
                self.logger.info("discovery_sql: conexión cerrada")
            except pyodbc.Error as exc:
                self.logger.warning(
                    "discovery_sql: error al cerrar conexión (ignorado): {}", exc
                )
        return df

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
                "discovery_sql: conectando a {}/{} (timeout {}s)",
                cred.server,
                cred.database,
                cred.connection_timeout,
            )
            conn = pyodbc.connect(conn_str, timeout=cred.connection_timeout)
        except pyodbc.Error as exc:
            raise LoaderError(
                f"discovery_sql: no se pudo conectar a "
                f"{cred.server}/{cred.database}: {exc}"
            ) from exc
        conn.timeout = cred.query_timeout
        return conn

    def _run_sp(self, conn: pyodbc.Connection) -> pd.DataFrame:
        """Ejecuta el SP y devuelve su DataFrame crudo."""
        self.logger.info("discovery_sql: ejecutando {}", _SP_DISCOVERY)
        start = time.perf_counter()
        try:
            df = pd.read_sql(_SP_DISCOVERY, conn)
        except pyodbc.Error as exc:
            raise LoaderError(
                f"discovery_sql: SP ({_SP_DISCOVERY}) falló: {exc}"
            ) from exc
        elapsed = time.perf_counter() - start
        self.logger.info(
            "discovery_sql: SP → {} filas en {:.2f}s", len(df), elapsed
        )
        if len(df) == 0:
            self.logger.warning(
                "discovery_sql: SP retornó 0 filas, posible anomalía"
            )
        return df
