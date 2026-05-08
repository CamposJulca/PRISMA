"""Excepciones del dominio PRISMA-GTI.

Define la jerarquía de errores que las distintas capas del pipeline
levantan. Todas heredan de :class:`PrismaError` para permitir captura
genérica en la CLI y manejo diferenciado por capa donde sea necesario.
"""

from __future__ import annotations


class PrismaError(Exception):
    """Excepción base de PRISMA-GTI."""


class ConfigurationError(PrismaError):
    """Error de configuración: YAML inválido, variable de entorno faltante."""


class LoaderError(PrismaError):
    """Fallo al cargar datos desde una fuente (SQL, LDAP, archivo)."""


class IdentityResolutionError(PrismaError):
    """No se pudo resolver una identidad y la política exige abortar.

    Por defecto el resolver no aborta — registra WARNING y continúa.
    Esta excepción queda disponible para configuraciones más estrictas.
    """


class TransformerError(PrismaError):
    """Fallo en una transformación: validación de schema, conversión, cálculo."""


class WriterError(PrismaError):
    """Fallo al persistir datos (Excel, Parquet, archivo intermedio)."""
