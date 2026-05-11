"""Capa identity: resolución de identidades por cédula y username.

Implementa la estrategia validada empíricamente en Fase 2:
**Kactus primero, LDAP solo para residuales, manual_overrides como
respaldo final** (ver ``docs/arquitectura.md`` §4.3 y
``docs/fase2_profiling.md`` §5.2).

Componentes
-----------

- :class:`KactusIndex` / :func:`build_kactus_index` — índices de
  lookup O(1) sobre el DataFrame de Kactus.
- :class:`LdapResolver` / :class:`LdapResolutionResult` — wrapper de
  conveniencia sobre :class:`LdapClient` para dedupe + batch.
- :class:`ManualOverrides` / :class:`NombrePorUsername` /
  :func:`load_manual_overrides` — carga del YAML de excepciones.
- :class:`IdentityResolver` / :class:`IdentityResolutionStats` /
  :class:`DisplayNameStats` — orquestador que compone las tres
  piezas anteriores.
"""

from prisma_gti.identity.kactus_index import KactusIndex, build_kactus_index
from prisma_gti.identity.ldap_cache import LdapResolutionResult, LdapResolver
from prisma_gti.identity.manual_overrides import (
    ManualOverrides,
    NombrePorUsername,
    load_manual_overrides,
)
from prisma_gti.identity.resolver import (
    DisplayNameStats,
    IdentityResolutionStats,
    IdentityResolver,
)

__all__ = [
    "DisplayNameStats",
    "IdentityResolutionStats",
    "IdentityResolver",
    "KactusIndex",
    "LdapResolutionResult",
    "LdapResolver",
    "ManualOverrides",
    "NombrePorUsername",
    "build_kactus_index",
    "load_manual_overrides",
]
