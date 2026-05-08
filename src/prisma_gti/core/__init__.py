"""Capa core: infraestructura transversal de PRISMA-GTI.

Reúne configuración, secretos, logging y excepciones del dominio para
que el resto del pipeline (loaders, identity, transformers, pipelines,
writers) consuma una API estable.
"""

from prisma_gti.core.config import (
    BatchSizes,
    CatalogConfig,
    CutoffDates,
    Paths,
    Settings,
    load_settings,
)
from prisma_gti.core.exceptions import (
    ConfigurationError,
    IdentityResolutionError,
    LoaderError,
    PrismaError,
    TransformerError,
    WriterError,
)
from prisma_gti.core.logger import configure_logging, get_logger
from prisma_gti.core.secrets import (
    ExternalUrls,
    LdapCredential,
    Secrets,
    SqlServerCredential,
    load_secrets,
)

__all__ = [
    "BatchSizes",
    "CatalogConfig",
    "ConfigurationError",
    "CutoffDates",
    "ExternalUrls",
    "IdentityResolutionError",
    "LdapCredential",
    "LoaderError",
    "Paths",
    "PrismaError",
    "Secrets",
    "Settings",
    "SqlServerCredential",
    "TransformerError",
    "WriterError",
    "configure_logging",
    "get_logger",
    "load_secrets",
    "load_settings",
]
