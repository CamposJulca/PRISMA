"""Loader de la tabla auxiliar ``USUARIOS`` de ArandaDB8.

Es la tercera fuente de identidades (después de Kactus y LDAP)
usada por el notebook legacy (bloque 32) para completar nombres
de display residuales::

    select UNAME as NombreCompleto,
           IDENTITY_NUMBER as cedula,
           USERNAME as username
    from USUARIOS
    order by UNAME

El resultado tiene el mismo esquema que :class:`KactusSqlLoader`
(``NombreCompleto``, ``cedula``, ``username``), por lo que el
pipeline puede concatenarlo al DataFrame de Kactus antes de
construir el :class:`KactusIndex` — enriqueciendo el índice sin
modificar la capa ``identity/``.
"""

from __future__ import annotations

import time
import warnings
from typing import Final

import pandas as pd
import pyodbc

from prisma_gti.core import LoaderError, SqlServerCredential
from prisma_gti.loaders.base import BaseLoader

warnings.filterwarnings(
    "ignore",
    message="pandas only supports SQLAlchemy.*",
    category=UserWarning,
)


_QUERY_ARANDA_USERS: Final[str] = (
    "select UNAME as NombreCompleto, "
    "IDENTITY_NUMBER as cedula, "
    "USERNAME as username "
    "from USUARIOS order by UNAME"
)


class ArandaUsersLoader(BaseLoader):
    """Carga la tabla auxiliar ``USUARIOS`` de ArandaDB8.

    Diseñada para complementar el catálogo de Kactus: cuando se
    concatena con el DataFrame de Kactus antes de
    :func:`build_kactus_index`, el índice resultante cubre tanto
    los empleados activos (Kactus) como las cuentas históricas que
    quedaron registradas únicamente en Aranda (USUARIOS).
    """

    def __init__(self, credentials: SqlServerCredential) -> None:
        super().__init__()
        self._credentials = credentials

    def load(self) -> pd.DataFrame:
        """Conecta, ejecuta la consulta y cierra la conexión.

        Retorna
        -------
        pd.DataFrame
            DataFrame con columnas ``NombreCompleto``, ``cedula`` y
            ``username``.

        Lanza
        -----
        LoaderError
            Si la conexión falla o si la consulta arroja error.
        """
        conn = self._open_connection()
        try:
            df = self._run_query(conn)
        finally:
            try:
                conn.close()
                self.logger.info("aranda_users_sql: conexión cerrada")
            except pyodbc.Error as exc:
                self.logger.warning(
                    "aranda_users_sql: error al cerrar conexión (ignorado): {}",
                    exc,
                )
        return df

    def _open_connection(self) -> pyodbc.Connection:
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
                "aranda_users_sql: conectando a {}/{} (timeout {}s)",
                cred.server,
                cred.database,
                cred.connection_timeout,
            )
            conn = pyodbc.connect(conn_str, timeout=cred.connection_timeout)
        except pyodbc.Error as exc:
            raise LoaderError(
                f"aranda_users_sql: no se pudo conectar a "
                f"{cred.server}/{cred.database}: {exc}"
            ) from exc
        conn.timeout = cred.query_timeout
        return conn

    def _run_query(self, conn: pyodbc.Connection) -> pd.DataFrame:
        self.logger.info(
            "aranda_users_sql: ejecutando consulta de USUARIOS"
        )
        start = time.perf_counter()
        try:
            df = pd.read_sql(_QUERY_ARANDA_USERS, conn)
        except pyodbc.Error as exc:
            raise LoaderError(
                f"aranda_users_sql: consulta USUARIOS falló: {exc}"
            ) from exc
        elapsed = time.perf_counter() - start
        self.logger.info(
            "aranda_users_sql: query → {} filas en {:.2f}s",
            len(df),
            elapsed,
        )
        if len(df) == 0:
            self.logger.warning(
                "aranda_users_sql: query retornó 0 filas, posible anomalía"
            )
        return df
