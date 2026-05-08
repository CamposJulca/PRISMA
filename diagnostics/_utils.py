"""
Utilidades compartidas por todos los scripts de diagnóstico.

Centraliza:
- Carga de variables de entorno desde .env
- Funciones de formato para output legible en terminal
- Helper para guardar evidencia en markdown
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Carga de .env desde la raíz del proyecto
try:
    from dotenv import load_dotenv

    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    ENV_PATH = PROJECT_ROOT / ".env"
    if ENV_PATH.exists():
        load_dotenv(ENV_PATH)
    else:
        print(f"⚠  No se encontró {ENV_PATH}. Verificar configuración.")
except ImportError:
    print("⚠  python-dotenv no está instalado. Las variables del .env no se cargarán.")
    PROJECT_ROOT = Path(__file__).resolve().parent.parent

RESULTADOS_DIR = PROJECT_ROOT / "diagnostics" / "resultados"
RESULTADOS_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================================
# Formato de output a terminal
# ============================================================================

ANCHO = 78


def header(titulo: str, script_id: str = "") -> None:
    """Imprime el encabezado de un script de diagnóstico."""
    print()
    print("=" * ANCHO)
    if script_id:
        print(f"  {script_id} — {titulo}")
    else:
        print(f"  {titulo}")
    print("=" * ANCHO)
    print(f"  Iniciado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * ANCHO)
    print()


def seccion(titulo: str) -> None:
    """Imprime un separador de sección."""
    print()
    print("-" * ANCHO)
    print(f"  {titulo}")
    print("-" * ANCHO)


def metrica(etiqueta: str, valor: Any, unidad: str = "") -> None:
    """Imprime una métrica con formato alineado."""
    valor_str = f"{valor}{' ' + unidad if unidad else ''}"
    print(f"  {etiqueta:<50} {valor_str}")


def conclusion(texto: str) -> None:
    """Imprime un bloque de conclusión tentativa al final del script."""
    print()
    print("=" * ANCHO)
    print("  CONCLUSIÓN TENTATIVA")
    print("=" * ANCHO)
    for linea in texto.strip().split("\n"):
        print(f"  {linea}")
    print("=" * ANCHO)
    print()


def error(mensaje: str, abortar: bool = True) -> None:
    """Reporta un error y opcionalmente termina el script."""
    print()
    print("✗ " + "=" * (ANCHO - 2))
    print(f"  ERROR: {mensaje}")
    print("✗ " + "=" * (ANCHO - 2))
    if abortar:
        sys.exit(1)


def warn(mensaje: str) -> None:
    """Imprime un warning."""
    print(f"  ⚠  {mensaje}")


def ok(mensaje: str) -> None:
    """Imprime confirmación."""
    print(f"  ✓ {mensaje}")


# ============================================================================
# Persistencia de resultados
# ============================================================================


def guardar_resultado(script_id: str, contenido: str) -> Path:
    """
    Guarda los resultados de un script en diagnostics/resultados/ con timestamp.
    Retorna la ruta del archivo creado.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre = f"{script_id}_{timestamp}.md"
    ruta = RESULTADOS_DIR / nombre
    ruta.write_text(contenido, encoding="utf-8")
    print(f"  💾 Resultado guardado en: {ruta.relative_to(PROJECT_ROOT)}")
    return ruta


# ============================================================================
# Lectura de variables de entorno con validación
# ============================================================================


def env(variable: str, default: str | None = None, requerida: bool = True) -> str:
    """
    Lee una variable de entorno. Si es requerida y no existe, aborta el script.
    """
    valor = os.getenv(variable, default)
    if requerida and not valor:
        error(
            f"Variable de entorno '{variable}' no está definida.\n"
            f"  Verificar el archivo .env (ver .env.example como referencia)."
        )
    return valor or ""


# ============================================================================
# Helper para mediciones de tiempo
# ============================================================================


class Cronometro:
    """Context manager simple para medir tiempo."""

    def __init__(self, etiqueta: str = "") -> None:
        self.etiqueta = etiqueta
        self.inicio: float = 0.0
        self.duracion: float = 0.0

    def __enter__(self) -> "Cronometro":
        import time

        self.inicio = time.perf_counter()
        return self

    def __exit__(self, *args: Any) -> None:
        import time

        self.duracion = time.perf_counter() - self.inicio
        if self.etiqueta:
            print(f"  ⏱  {self.etiqueta}: {self.duracion:.3f}s")

    @property
    def ms(self) -> float:
        return self.duracion * 1000


def formato_tiempo(segundos: float) -> str:
    """Formatea segundos en notación legible (ms si <1s, s si >=1s)."""
    if segundos < 1:
        return f"{segundos * 1000:.1f} ms"
    if segundos < 60:
        return f"{segundos:.2f} s"
    minutos = int(segundos // 60)
    seg_restantes = segundos % 60
    return f"{minutos}m {seg_restantes:.1f}s"