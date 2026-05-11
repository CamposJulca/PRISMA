"""Capa de loaders: adquisición de datos crudos por fuente.

Loaders disponibles:

- :class:`BaseLoader` — interfaz común para todos los loaders.
- :class:`LdapClient` — cliente LDAP con conexión persistente y batch.
- :class:`ArandaSqlLoader` / :class:`ArandaSqlResult` — los 3 SP de
  ArandaDB8 (incidentes, requerimientos, cambios).
- :class:`ArandaUsersLoader` — tabla auxiliar ``USUARIOS`` de
  ArandaDB8 (catálogo histórico de cuentas).
- :class:`DiscoverySqlLoader` — SP ``SP_CASOS_DISCOVERYGTI_V1`` de
  DiscovSQL.
- :class:`KactusSqlLoader` — tabla maestra de empleados desde Kactus.
- :class:`GlpiCsvLoader` — export ``GLPI.csv``.
- :class:`GeusExcelLoader` — export ``GEUS.xlsx``.
- :class:`AsmsCsvLoader` / :class:`AsmsCsvResult` — los 4 CSVs de
  Aranda ASMS (incidentes, requerimientos, cambios, tareas).
- :class:`StefaniniCsvLoader` / :class:`StefaniniCsvResult` — los 4
  CSVs de Stefanini (incidentes, requerimientos, problemas, cambios).
- :class:`UsuariosCsvLoader` — diccionario auxiliar
  username_ufinal ↔ usuariofinal.
- :class:`EspecialistasCsvLoader` — diccionario auxiliar
  username_resp ↔ responsable.
"""

from prisma_gti.loaders.aranda_sql import ArandaSqlLoader, ArandaSqlResult
from prisma_gti.loaders.aranda_users_sql import ArandaUsersLoader
from prisma_gti.loaders.asms_csv import AsmsCsvLoader, AsmsCsvResult
from prisma_gti.loaders.base import BaseLoader
from prisma_gti.loaders.discovery_sql import DiscoverySqlLoader
from prisma_gti.loaders.especialistas_csv import EspecialistasCsvLoader
from prisma_gti.loaders.geus_excel import GeusExcelLoader
from prisma_gti.loaders.glpi_csv import GlpiCsvLoader
from prisma_gti.loaders.kactus_sql import KactusSqlLoader
from prisma_gti.loaders.ldap_client import LdapClient
from prisma_gti.loaders.stefanini_csv import (
    StefaniniCsvLoader,
    StefaniniCsvResult,
)
from prisma_gti.loaders.usuarios_csv import UsuariosCsvLoader

__all__ = [
    "ArandaSqlLoader",
    "ArandaSqlResult",
    "ArandaUsersLoader",
    "AsmsCsvLoader",
    "AsmsCsvResult",
    "BaseLoader",
    "DiscoverySqlLoader",
    "EspecialistasCsvLoader",
    "GeusExcelLoader",
    "GlpiCsvLoader",
    "KactusSqlLoader",
    "LdapClient",
    "StefaniniCsvLoader",
    "StefaniniCsvResult",
    "UsuariosCsvLoader",
]
