"""Cliente LDAP optimizado para resolución batch de identidades.

Reemplaza el patrón del notebook legacy (una conexión por búsqueda)
por una conexión persistente + filtros OR en chunks + cache local.
La estrategia fue validada empíricamente en Fase 2 con un speedup de
47× sobre el patrón anterior (ver docs/fase2_profiling.md §3.5).

Esta clase **no hereda** de :class:`BaseLoader` — es una utilidad
consumida por la capa ``identity/`` para resolver cédulas y
usernames; no devuelve un DataFrame.

Política de cache
-----------------
El cache (``_cache_cedulas`` y ``_cache_usernames``) está scope-eado a
la instancia y **persiste entre ciclos** de :meth:`connect`/
:meth:`close`. Para limpiarlo explícitamente cuando se necesite
(por ejemplo, al inicio de una nueva corrida del pipeline), llamar
:meth:`clear_cache`.
"""

from __future__ import annotations

from collections.abc import Iterable
from types import TracebackType
from typing import Self

from ldap3 import SIMPLE, SUBTREE, Connection, Server
from ldap3.core.exceptions import LDAPException
from ldap3.utils.conv import escape_filter_chars

from prisma_gti.core import LdapCredential, LoaderError, get_logger

logger = get_logger(__name__)


class LdapClient:
    """Cliente LDAP con conexión persistente, búsqueda batch y cache.

    Uso típico::

        with LdapClient(credentials) as ldap:
            usernames = ldap.resolve_cedulas_to_usernames(["123", "456"])

    El context manager garantiza el cierre de la conexión incluso si
    una excepción interrumpe la operación. El cache de resoluciones
    sobrevive al cierre y puede reaprovecharse en un próximo
    ``connect`` sobre la misma instancia.
    """

    def __init__(
        self,
        credentials: LdapCredential,
        batch_size: int | None = None,
    ) -> None:
        """Inicializa el cliente sin abrir conexión.

        Parámetros
        ----------
        credentials : LdapCredential
            Configuración de servidor, base DN, usuario, password,
            batch_size por defecto y timeout.
        batch_size : int | None
            Override del tamaño de chunk para los filtros OR. Si es
            ``None`` se usa ``credentials.batch_size``.
        """
        self._credentials = credentials
        self._batch_size = batch_size if batch_size is not None else credentials.batch_size
        self._connection: Connection | None = None
        self._cache_cedulas: dict[str, str] = {}
        self._cache_usernames: dict[str, str] = {}

    # ---- Lifecycle ------------------------------------------------------

    def connect(self) -> None:
        """Abre la conexión persistente al servidor LDAP.

        Lanza
        -----
        LoaderError
            Si el bind LDAP falla (credenciales inválidas, servidor
            inalcanzable, timeout).
        """
        if self._connection is not None and self._connection.bound:
            return
        try:
            server = Server(self._credentials.server, connect_timeout=self._credentials.timeout)
            self._connection = Connection(
                server,
                user=self._credentials.user,
                password=self._credentials.password,
                authentication=SIMPLE,
                auto_bind=True,
                raise_exceptions=True,
                receive_timeout=self._credentials.timeout,
            )
            logger.info(
                "ldap_client: conexión establecida a {} (base_dn={})",
                self._credentials.server,
                self._credentials.base_dn,
            )
        except LDAPException as exc:
            self._connection = None
            raise LoaderError(f"LDAP bind falló: {exc}") from exc

    def close(self) -> None:
        """Cierra la conexión LDAP. Idempotente. **No** limpia el cache."""
        if self._connection is None:
            return
        try:
            self._connection.unbind()
        except LDAPException as exc:
            logger.warning("ldap_client: error al cerrar conexión (ignorado): {}", exc)
        finally:
            self._connection = None
            logger.info("ldap_client: conexión cerrada")

    def clear_cache(self) -> None:
        """Vacía las dos tablas de cache de resoluciones."""
        self._cache_cedulas.clear()
        self._cache_usernames.clear()
        logger.info("ldap_client: cache de resoluciones vaciado")

    def __enter__(self) -> Self:
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()

    # ---- Public resolution API ------------------------------------------

    def resolve_cedulas_to_usernames(
        self, cedulas: Iterable[str]
    ) -> dict[str, str]:
        """Resuelve cédulas a ``sAMAccountName`` vía ``employeeID``.

        Parámetros
        ----------
        cedulas : Iterable[str]
            Cédulas a buscar. Se deduplican antes de consultar y se
            ignoran las vacías o ``None``.

        Retorna
        -------
        dict[str, str]
            Mapa ``{cedula: sAMAccountName}`` solo con las cédulas
            efectivamente encontradas en el directorio. Las no
            encontradas no aparecen en el dict.
        """
        return self._resolve_batch(
            inputs=cedulas,
            cache=self._cache_cedulas,
            attribute_in="employeeID",
            attribute_out="sAMAccountName",
            label="cedulas",
        )

    def resolve_usernames_to_displaynames(
        self, usernames: Iterable[str]
    ) -> dict[str, str]:
        """Resuelve ``sAMAccountName`` a ``displayName``.

        Mismo patrón que :meth:`resolve_cedulas_to_usernames` pero
        invertido: la entrada es el username y la salida el nombre
        para mostrar.
        """
        return self._resolve_batch(
            inputs=usernames,
            cache=self._cache_usernames,
            attribute_in="sAMAccountName",
            attribute_out="displayName",
            label="usernames",
        )

    # ---- Internals ------------------------------------------------------

    def _resolve_batch(
        self,
        inputs: Iterable[str],
        cache: dict[str, str],
        attribute_in: str,
        attribute_out: str,
        label: str,
    ) -> dict[str, str]:
        """Lógica común a las dos resoluciones públicas."""
        unique_inputs = {v.strip() for v in inputs if v and str(v).strip()}
        if not unique_inputs:
            return {}

        cached_hits = {v: cache[v] for v in unique_inputs if v in cache}
        pending = [v for v in unique_inputs if v not in cache]

        logger.info(
            "ldap_client: resolviendo {} {} (cache hits: {}, pendientes: {})",
            len(unique_inputs),
            label,
            len(cached_hits),
            len(pending),
        )

        if not pending:
            return cached_hits

        self._ensure_connected()
        results: dict[str, str] = dict(cached_hits)
        for chunk in _chunked(pending, self._batch_size):
            chunk_results = self._search_chunk(
                attribute_in=attribute_in,
                values=chunk,
                attribute_out=attribute_out,
                retry=True,
            )
            results.update(chunk_results)
            cache.update(chunk_results)
            logger.info(
                "ldap_client: chunk de {} {} → {} resueltos",
                len(chunk),
                label,
                len(chunk_results),
            )

        return results

    def _ensure_connected(self) -> Connection:
        """Devuelve la conexión activa o levanta LoaderError."""
        if self._connection is None or not self._connection.bound:
            raise LoaderError(
                "LDAP: la conexión no está abierta. Usa connect() o el "
                "context manager `with LdapClient(...) as c:`."
            )
        return self._connection

    def _search_chunk(
        self,
        attribute_in: str,
        values: list[str],
        attribute_out: str,
        retry: bool,
    ) -> dict[str, str]:
        """Ejecuta una búsqueda batch con filtro OR.

        En caso de :class:`LDAPException` durante la búsqueda, se
        intenta una vez más reabriendo la conexión. Si falla de nuevo
        se levanta :class:`LoaderError`.
        """
        try:
            return self._do_search(attribute_in, values, attribute_out)
        except LDAPException as exc:
            if not retry:
                raise LoaderError(
                    f"LDAP search falló (sin reintento): {exc}"
                ) from exc
            logger.warning(
                "ldap_client: error en search ({}), reintentando con reconexión",
                exc,
            )
            self.close()
            self.connect()
            try:
                return self._do_search(attribute_in, values, attribute_out)
            except LDAPException as exc_retry:
                raise LoaderError(
                    f"LDAP batch falló tras reintento: {exc_retry}"
                ) from exc_retry

    def _do_search(
        self,
        attribute_in: str,
        values: list[str],
        attribute_out: str,
    ) -> dict[str, str]:
        """Construye el filtro y ejecuta la búsqueda contra LDAP."""
        conn = self._ensure_connected()
        escaped = [escape_filter_chars(v) for v in values]
        or_clause = "".join(f"({attribute_in}={v})" for v in escaped)
        search_filter = f"(&(objectClass=user)(|{or_clause}))"

        conn.search(
            search_base=self._credentials.base_dn,
            search_filter=search_filter,
            search_scope=SUBTREE,
            attributes=[attribute_in, attribute_out],
        )

        mapped: dict[str, str] = {}
        duplicates: list[str] = []
        for entry in conn.entries:
            if attribute_in not in entry or attribute_out not in entry:
                continue
            key = entry[attribute_in].value
            value = entry[attribute_out].value
            if key is None or value is None:
                continue
            key_str = str(key)
            value_str = str(value)
            if key_str in mapped and mapped[key_str] != value_str:
                duplicates.append(key_str)
            mapped[key_str] = value_str

        if duplicates:
            logger.warning(
                "ldap_client: {} valores devolvieron entradas duplicadas con "
                "{} distinto (gana el último): {}",
                len(duplicates),
                attribute_out,
                duplicates,
            )
        return mapped


def _chunked(items: list[str], size: int) -> Iterable[list[str]]:
    """Particiona ``items`` en sub-listas de a lo sumo ``size`` elementos."""
    for i in range(0, len(items), size):
        yield items[i : i + size]
