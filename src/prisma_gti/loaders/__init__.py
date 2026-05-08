"""Capa de loaders: adquisición de datos crudos por fuente.

Esta primera tanda expone:

- :class:`BaseLoader` — interfaz común para todos los loaders.
- :class:`LdapClient` — cliente LDAP con conexión persistente y batch.
- :class:`ArandaSqlLoader` y :class:`ArandaSqlResult` — los 3 SP de
  ArandaDB8.

Las demás fuentes (Discovery, Kactus, GLPI, GEUS, Stefanini, ASMS) se
implementarán en sesiones siguientes.
"""

from prisma_gti.loaders.aranda_sql import ArandaSqlLoader, ArandaSqlResult
from prisma_gti.loaders.base import BaseLoader
from prisma_gti.loaders.ldap_client import LdapClient

__all__ = [
    "ArandaSqlLoader",
    "ArandaSqlResult",
    "BaseLoader",
    "LdapClient",
]
