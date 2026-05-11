"""Wrapper de conveniencia sobre :class:`LdapClient` para el resolver.

Decisión de diseño — **no es un cache de disco**. El cliente LDAP ya
mantiene su propio cache en memoria scope-eado a la instancia
(:attr:`LdapClient._cache_cedulas` / :attr:`_cache_usernames`). Este
módulo es una capa por encima que:

1. Recibe un ``Iterable[str | None]`` potencialmente con duplicados,
   ``None`` y valores vacíos.
2. Deduplica y filtra valores válidos (no vacíos, no ``None``).
3. Hace **una sola llamada batch** al :class:`LdapClient`.
4. Retorna el dict de resultados + métricas (``resolved`` vs
   ``unresolved``) para que el resolver agregue stats sin recomputar.

El módulo NO abre ni cierra la conexión LDAP. El caller es
responsable de pasar un :class:`LdapClient` ya conectado, idealmente
vía ``with LdapClient(...) as client:``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from prisma_gti.core import get_logger
from prisma_gti.loaders import LdapClient

logger = get_logger(__name__)


@dataclass(frozen=True)
class LdapResolutionResult:
    """Resultado tipado de una resolución batch contra LDAP.

    Atributos
    ---------
    resolved : dict[str, str]
        Mapeo entrada → salida solo de las que LDAP encontró.
    unresolved : set[str]
        Entradas únicas válidas que LDAP no encontró.
    total_queried : int
        Número de entradas únicas válidas enviadas a LDAP (es decir,
        ``len(resolved) + len(unresolved)``). Útil para calcular ratio
        de cobertura.
    """

    resolved: dict[str, str]
    unresolved: set[str]
    total_queried: int


class LdapResolver:
    """Capa de conveniencia sobre :class:`LdapClient`.

    Uso típico::

        with LdapClient(credentials) as client:
            resolver = LdapResolver(client)
            result = resolver.resolve_cedulas(["123", None, "123", "456"])
            # result.resolved → {"123": "user1", "456": "user2"}
            # result.unresolved → set() o subset no encontrado

    No mantiene estado propio: delega cache y conexión al cliente.
    """

    def __init__(self, ldap_client: LdapClient) -> None:
        self._client = ldap_client

    def resolve_cedulas(
        self, cedulas: Iterable[str | None]
    ) -> LdapResolutionResult:
        """Resuelve cédulas (``employeeID``) a ``sAMAccountName``.

        Deduplica, filtra ``None``/vacíos, llama a LDAP UNA sola vez
        y empaqueta el resultado en :class:`LdapResolutionResult`.
        Si el set deduplicado es vacío, retorna un resultado vacío
        sin tocar LDAP.
        """
        return self._resolve(
            inputs=cedulas,
            label="cedulas",
            method=self._client.resolve_cedulas_to_usernames,
        )

    def resolve_usernames_to_displaynames(
        self, usernames: Iterable[str | None]
    ) -> LdapResolutionResult:
        """Resuelve ``sAMAccountName`` a ``displayName``.

        Mismo patrón que :meth:`resolve_cedulas` con la otra API del
        cliente.
        """
        return self._resolve(
            inputs=usernames,
            label="usernames",
            method=self._client.resolve_usernames_to_displaynames,
        )

    def _resolve(
        self,
        inputs: Iterable[str | None],
        label: str,
        method,
    ) -> LdapResolutionResult:
        """Lógica común de dedupe + filtrado + invocación + empaquetado."""
        unique_valid = {
            str(v).strip() for v in inputs if v is not None and str(v).strip()
        }

        if not unique_valid:
            logger.info(
                "ldap_resolver: 0 {} válidas tras dedupe; LDAP no se consulta",
                label,
            )
            return LdapResolutionResult(
                resolved={},
                unresolved=set(),
                total_queried=0,
            )

        logger.info(
            "ldap_resolver: resolviendo {} {} únicas vía batch LDAP",
            len(unique_valid),
            label,
        )

        resolved = method(unique_valid)
        unresolved = unique_valid - resolved.keys()

        logger.info(
            "ldap_resolver: {}/{} {} resueltas ({} no encontradas)",
            len(resolved),
            len(unique_valid),
            label,
            len(unresolved),
        )

        return LdapResolutionResult(
            resolved=resolved,
            unresolved=unresolved,
            total_queried=len(unique_valid),
        )
