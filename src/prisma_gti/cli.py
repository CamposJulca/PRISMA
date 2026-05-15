"""PRISMA-GTI — Entry point del CLI principal.

Expone los cuatro comandos que el equipo de operaciones ejecuta en
producción:

- ``prisma historico``   → :class:`HistoricoPipeline` → ``indicators1.xlsx``.
- ``prisma stefanini``   → :class:`StefaniniPipeline` → ``provisionalASMS.xlsx``
  y ``tareas1.xlsx``.
- ``prisma ml-models``   → :class:`MLPipeline` → 3 archivos predictivos.
- ``prisma run-all``     → los tres en orden secuencial.

Comportamientos transversales
-----------------------------

- **Logging dual**: cada corrida genera un archivo
  ``<log_dir>/prisma_YYYYMMDD_HHMMSS_<comando>.log`` con nivel DEBUG
  (todo el detalle). La consola usa el nivel definido en ``LOG_LEVEL``
  del ``.env`` (default ``INFO``).
- **Códigos de salida**:

  - ``0`` — ejecución exitosa.
  - ``1`` — algún pipeline falló durante ejecución (errores del dominio
    ``PrismaError`` o excepciones no esperadas).
  - ``2`` — error de configuración (``ConfigurationError``: credenciales
    faltantes, ``.env`` inválido, archivos de input no encontrados a
    nivel de configuración).

- **Reporte final amigable**: tras éxito se imprime un resumen con los
  archivos generados, filas totales y tiempo. Tras fallo se imprime el
  tipo y mensaje de la excepción más la ruta del log detallado.

- **Orden estricto en ``run-all``**: ``historico`` → ``stefanini`` →
  ``ml-models``. Si alguno de los dos primeros falla, los siguientes
  NO se ejecutan (``ml-models`` depende de ``indicators1.xlsx`` que
  produce ``historico``).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Final

import typer
from loguru import logger as _logger

from prisma_gti.core import (
    ConfigurationError,
    PrismaError,
    Secrets,
    Settings,
    configure_logging,
    get_logger,
    load_secrets,
    load_settings,
)
from prisma_gti.pipelines import (
    HistoricoPipeline,
    MLPipeline,
    StefaniniPipeline,
)

logger = get_logger(__name__)


_EXIT_OK: Final[int] = 0
_EXIT_PIPELINE_ERROR: Final[int] = 1
_EXIT_CONFIG_ERROR: Final[int] = 2

# Formato compacto sin colores para el sink de archivo (loguru ANSI
# tags no se rinden bien al leer un .log en un editor).
_FILE_LOG_FORMAT: Final[str] = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
    "{extra[module]} | {message}"
)


app = typer.Typer(
    name="prisma",
    help=(
        "PRISMA — Plataforma de Reportes e Indicadores de Servicios y "
        "Mesa de Atención (FINAGRO GTI)."
    ),
    no_args_is_help=True,
    add_completion=False,
)


# ---- Tipo del runner que pasa cada comando a _execute ---------------------

# Cada runner ejecuta el (o los) pipelines y retorna una lista de
# tuplas (ruta_str, filas) que el reporte final usa para presentar el
# resumen al usuario.
Runner = Callable[[Settings, Secrets], list[tuple[str, int]]]


# ---- Setup ----------------------------------------------------------------


def _setup_logging(
    settings: Settings,
    secrets: Secrets,
    command_name: str,
) -> Path:
    """Configura los dos sinks de logging y retorna la ruta del archivo.

    El sink de consola usa ``secrets.log_level`` (típicamente INFO);
    el sink de archivo usa nivel DEBUG para captar todo el detalle.
    ``configure_logging`` se llama con ``log_file=None`` porque
    queremos un sink de archivo separado por corrida — no el archivo
    de log rutinario del sistema.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = settings.paths.log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file_path = log_dir / f"prisma_{timestamp}_{command_name}.log"

    configure_logging(
        config_path=None,
        level=secrets.log_level,
        log_file=None,
    )

    _logger.add(
        str(log_file_path),
        level="DEBUG",
        format=_FILE_LOG_FORMAT,
        backtrace=True,
        diagnose=False,
        encoding="utf-8",
        enqueue=True,
    )

    return log_file_path


def _load_config() -> tuple[Settings, Secrets]:
    """Carga ``.env`` + ``settings.yaml`` y los valida."""
    secrets = load_secrets()
    settings = load_settings(secrets=secrets)
    return settings, secrets


# ---- Reporte amigable -----------------------------------------------------


def _report_success(
    files: list[tuple[str, int]],
    duration: float,
    log_path: Path,
) -> None:
    """Imprime el resumen post-ejecución exitosa."""
    typer.echo()
    typer.secho("✓ PRISMA ejecutado exitosamente", fg=typer.colors.GREEN)
    typer.echo()
    typer.echo("Archivos generados:")
    max_path_len = max((len(path) for path, _ in files), default=0)
    for path_str, rows in files:
        typer.echo(f"  {path_str:<{max_path_len}}  ({rows:,} filas)")
    typer.echo()
    typer.echo(f"Tiempo total: {duration:.1f} segundos")
    typer.echo(f"Log detallado: {log_path}")


def _report_failure(
    command_name: str,
    exc: BaseException,
    log_path: Path | None,
) -> None:
    """Imprime un mensaje breve de falla y apunta al log si existe."""
    typer.echo()
    typer.secho(
        f"✗ PRISMA falló durante `{command_name}`",
        err=True,
        fg=typer.colors.RED,
    )
    typer.echo(
        f"  Error: {type(exc).__name__}: {exc}",
        err=True,
    )
    if log_path is not None:
        typer.echo(f"  Log detallado: {log_path}", err=True)
    else:
        typer.echo(
            "  Log no disponible (falla previa a la configuración del logger).",
            err=True,
        )


# ---- Núcleo de ejecución --------------------------------------------------


def _execute(command_name: str, runner: Runner) -> None:
    """Ejecuta un runner con manejo unificado de errores y reporte.

    Mapea excepciones a los códigos de salida documentados en el
    docstring del módulo. El traceback completo se persiste en el
    archivo de log (nivel DEBUG) vía ``logger.exception``.
    """
    log_path: Path | None = None
    try:
        settings, secrets = _load_config()
        log_path = _setup_logging(settings, secrets, command_name)

        logger.info("cli: comando `{}` iniciado", command_name)
        start = time.perf_counter()
        files = runner(settings, secrets)
        duration = time.perf_counter() - start
        logger.info(
            "cli: comando `{}` completado en {:.1f}s", command_name, duration
        )

        _report_success(files, duration, log_path)
    except ConfigurationError as exc:
        if log_path is not None:
            logger.exception(
                "cli: configuración inválida en `{}`: {}", command_name, exc
            )
        _report_failure(command_name, exc, log_path)
        raise typer.Exit(_EXIT_CONFIG_ERROR) from exc
    except PrismaError as exc:
        if log_path is not None:
            logger.exception(
                "cli: error de dominio en `{}`: {}", command_name, exc
            )
        _report_failure(command_name, exc, log_path)
        raise typer.Exit(_EXIT_PIPELINE_ERROR) from exc
    except typer.Exit:
        raise
    except Exception as exc:
        if log_path is not None:
            logger.exception(
                "cli: error inesperado en `{}`: {}", command_name, exc
            )
        _report_failure(command_name, exc, log_path)
        raise typer.Exit(_EXIT_PIPELINE_ERROR) from exc


# ---- Comandos -------------------------------------------------------------


@app.command()
def historico() -> None:
    """Genera ``indicators1.xlsx`` consolidando Discovery + Aranda + GLPI + GEUS + ASMS."""

    def runner(settings: Settings, secrets: Secrets) -> list[tuple[str, int]]:
        result = HistoricoPipeline(settings, secrets).run()
        return [(str(result.indicators1_path), result.total_rows)]

    _execute("historico", runner)


@app.command()
def stefanini() -> None:
    """Genera ``provisionalASMS.xlsx`` y ``tareas1.xlsx`` desde los CSVs de Stefanini."""

    def runner(settings: Settings, secrets: Secrets) -> list[tuple[str, int]]:
        result = StefaniniPipeline(settings, secrets).run()
        return [
            (
                str(result.provisional_asms_path),
                result.total_provisional_rows,
            ),
            (str(result.tareas_path), result.total_tareas_rows),
        ]

    _execute("stefanini", runner)


@app.command(name="ml-models")
def ml_models() -> None:
    """Genera ``indicadoresPeriodo*.xlsx`` e ``indicadoresMX.xlsx`` (regresiones).

    Requiere ``indicators1.xlsx`` ya generado en ``data/output/``.
    Si no existe, falla con ``LoaderError`` indicando que hay que
    correr ``prisma historico`` primero.
    """

    def runner(settings: Settings, secrets: Secrets) -> list[tuple[str, int]]:
        result = MLPipeline(settings, secrets).run()
        return [
            (
                str(result.periodo_2025_path),
                result.total_periodo_2025_rows,
            ),
            (str(result.periodo_path), result.total_periodo_rows),
            (str(result.mx_path), result.total_mx_rows),
        ]

    _execute("ml-models", runner)


@app.command(name="run-all")
def run_all() -> None:
    """Ejecuta los tres pipelines en orden secuencial.

    Orden: ``historico`` → ``stefanini`` → ``ml-models``.

    Si ``historico`` falla, los siguientes pipelines NO se ejecutan
    (``ml-models`` consume su output). Si ``stefanini`` falla, tampoco
    se ejecuta ``ml-models``; queda como decisión conservadora para
    evitar generar reportes parciales mientras la fuente Stefanini
    está en estado inconsistente.
    """

    def runner(settings: Settings, secrets: Secrets) -> list[tuple[str, int]]:
        files: list[tuple[str, int]] = []

        # 1. Histórico — bloqueante. Si falla, abortamos todo.
        logger.info("cli: run-all paso 1/3 — HistoricoPipeline")
        hist = HistoricoPipeline(settings, secrets).run()
        files.append((str(hist.indicators1_path), hist.total_rows))

        # 2. Stefanini — bloqueante. Si falla, abortamos antes de ML.
        logger.info("cli: run-all paso 2/3 — StefaniniPipeline")
        stef = StefaniniPipeline(settings, secrets).run()
        files.extend(
            [
                (
                    str(stef.provisional_asms_path),
                    stef.total_provisional_rows,
                ),
                (str(stef.tareas_path), stef.total_tareas_rows),
            ]
        )

        # 3. ML models — último. Si falla, los outputs de 1 y 2 ya
        # están escritos en disco (el _report_failure los menciona en
        # el log pero no en el resumen final).
        logger.info("cli: run-all paso 3/3 — MLPipeline")
        ml = MLPipeline(settings, secrets).run()
        files.extend(
            [
                (
                    str(ml.periodo_2025_path),
                    ml.total_periodo_2025_rows,
                ),
                (str(ml.periodo_path), ml.total_periodo_rows),
                (str(ml.mx_path), ml.total_mx_rows),
            ]
        )

        return files

    _execute("run-all", runner)


if __name__ == "__main__":  # pragma: no cover
    app()
