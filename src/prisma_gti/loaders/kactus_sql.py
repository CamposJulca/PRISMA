"""Loader de la tabla maestra de empleados desde la BD Kactus.

Ejecuta una única consulta SQL sobre Kactus que produce el catálogo
de empleados con tres columnas — ``NombreCompleto``, ``cedula`` y
``username`` — usado aguas abajo por ``identity/`` para resolver
cédulas a usernames sin ir a LDAP (cubre el 88,4% de las cédulas
únicas según el script 08 de Fase 2).

Query literal extraída del notebook legacy ``ProyectoFinal3.ipynb``
celda 6. No se renombra ni se transforma nada — esa es responsabilidad
de los transformers.
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


_QUERY_KACTUS: Final[str] = (
    "select distinct "
    "RTRIM(emp.nom_empl) + ' ' + RTRIM(emp.ape_empl) as NombreCompleto, "
    "cast(emp.cod_empl as varchar(50)) as cedula, "
    "case when CHARINDEX('@', emp.box_mail) > 0 "
    "then left(emp.box_mail, CHARINDEX('@', emp.box_mail) - 1) "
    "else emp.box_mail end as username "
    "from gn_accaj gn "
    "inner join bi_emple emp on gn.COD_EMPL = emp.cod_empl "
    "where CHARINDEX('@', emp.box_mail) > 0 "
    "order by NombreCompleto"
)


class KactusSqlLoader(BaseLoader):
    """Carga la tabla maestra de empleados desde Kactus.

    El resultado tiene tres columnas (``NombreCompleto``, ``cedula``,
    ``username``) y es el insumo principal de la resolución de
    identidades. Cualquier fallo de conexión o de ejecución del query
    se traduce a :class:`LoaderError` cerrando la conexión limpiamente.
    """

    def __init__(self, credentials: SqlServerCredential) -> None:
        super().__init__()
        self._credentials = credentials

    def load(self) -> pd.DataFrame:
        """Conecta, ejecuta la consulta y cierra la conexión.

        Retorna
        -------
        pd.DataFrame
            Catálogo de empleados con columnas ``NombreCompleto``,
            ``cedula`` y ``username``.

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
                self.logger.info("kactus_sql: conexión cerrada")
            except pyodbc.Error as exc:
                self.logger.warning(
                    "kactus_sql: error al cerrar conexión (ignorado): {}", exc
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
                "kactus_sql: conectando a {}/{} (timeout {}s)",
                cred.server,
                cred.database,
                cred.connection_timeout,
            )
            conn = pyodbc.connect(conn_str, timeout=cred.connection_timeout)
        except pyodbc.Error as exc:
            raise LoaderError(
                f"kactus_sql: no se pudo conectar a "
                f"{cred.server}/{cred.database}: {exc}"
            ) from exc
        conn.timeout = cred.query_timeout
        return conn

    def _run_query(self, conn: pyodbc.Connection) -> pd.DataFrame:
        """Ejecuta la consulta y devuelve su DataFrame crudo."""
        self.logger.info("kactus_sql: ejecutando consulta maestra de empleados")
        start = time.perf_counter()
        try:
            df = pd.read_sql(_QUERY_KACTUS, conn)
        except pyodbc.Error as exc:
            raise LoaderError(
                f"kactus_sql: consulta maestra falló: {exc}"
            ) from exc
        elapsed = time.perf_counter() - start
        self.logger.info(
            "kactus_sql: query → {} filas en {:.2f}s", len(df), elapsed
        )
        if len(df) == 0:
            self.logger.warning(
                "kactus_sql: query retornó 0 filas, posible anomalía"
            )
        return df
