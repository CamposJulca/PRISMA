#!/usr/bin/env python3
"""
run_all — Ejecuta los 8 scripts de diagnóstico en secuencia y consolida
los resultados en un único reporte.

Uso:
    python diagnostics/run_all.py

    # Saltar scripts específicos:
    python diagnostics/run_all.py --skip 04 05

    # Modo rápido (no ejecutar los que tardan más):
    python diagnostics/run_all.py --rapido
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _utils import (
    ANCHO,
    PROJECT_ROOT,
    RESULTADOS_DIR,
    formato_tiempo,
    header,
    ok,
    seccion,
    warn,
)

DIAGNOSTICS_DIR = Path(__file__).resolve().parent

SCRIPTS = [
    ("01", "01_volumetria_fuentes.py", "Volumetría de fuentes"),
    ("02", "02_tiempo_conexiones.py", "Tiempo de conexiones"),
    ("03", "03_tiempo_lectura_csv.py", "Tiempo de lectura archivos"),
    ("04", "04_ldap_unitario.py", "LDAP unitario"),
    ("05", "05_ldap_batch.py", "LDAP batch (experimento clave)"),
    ("06", "06_iterrows_vs_vectorizado.py", "iterrows vs vectorizado"),
    ("07", "07_excel_vs_parquet.py", "Excel vs Parquet"),
    ("08", "08_perfil_kactus.py", "Perfil de Kactus"),
]

SCRIPTS_LENTOS = {"04", "05"}  # Los que pueden tardar más


def ejecutar_script(script_path: Path) -> tuple[int, float]:
    """Ejecuta un script y retorna (return_code, duracion_s)."""
    import time

    inicio = time.perf_counter()
    result = subprocess.run(
        [sys.executable, str(script_path)],
        capture_output=False,  # Que el output vaya directo a la terminal
    )
    duracion = time.perf_counter() - inicio
    return result.returncode, duracion


def main() -> None:
    parser = argparse.ArgumentParser(description="Ejecutor de la batería de diagnóstico PRISMA-GTI")
    parser.add_argument(
        "--skip",
        nargs="+",
        default=[],
        help="IDs de scripts a saltar (e.g. --skip 04 05)",
    )
    parser.add_argument(
        "--rapido",
        action="store_true",
        help="Ejecutar solo los rápidos (omite los pesados)",
    )
    args = parser.parse_args()

    skip = set(args.skip)
    if args.rapido:
        skip.update(SCRIPTS_LENTOS)

    header("Batería completa de diagnósticos PRISMA-GTI", "RUN_ALL")

    print(f"  Total de scripts: {len(SCRIPTS)}")
    if skip:
        print(f"  Saltando: {', '.join(sorted(skip))}")
    print(f"  Resultados se guardan en: {RESULTADOS_DIR.relative_to(PROJECT_ROOT)}/")
    print()

    inicio_global = datetime.now()
    resultados: list[tuple[str, str, int, float]] = []

    for script_id, script_name, descripcion in SCRIPTS:
        if script_id in skip:
            print()
            print("─" * ANCHO)
            print(f"  [{script_id}] {descripcion} — SALTADO")
            print("─" * ANCHO)
            continue

        script_path = DIAGNOSTICS_DIR / script_name
        if not script_path.exists():
            warn(f"  Script {script_path} no encontrado.")
            continue

        try:
            rc, duracion = ejecutar_script(script_path)
            resultados.append((script_id, descripcion, rc, duracion))
            if rc == 0:
                print()
                ok(f"[{script_id}] OK en {formato_tiempo(duracion)}")
            else:
                print()
                warn(f"[{script_id}] FALLÓ con código {rc} en {formato_tiempo(duracion)}")
        except Exception as e:
            warn(f"  [{script_id}] Excepción: {e}")
            resultados.append((script_id, descripcion, -1, 0))

    # --- Resumen final ---
    duracion_total = (datetime.now() - inicio_global).total_seconds()

    seccion("Resumen final de la batería")
    print(f"  Tiempo total: {formato_tiempo(duracion_total)}")
    print()
    print(f"  {'ID':<5} {'Descripción':<40} {'Estado':<10} {'Tiempo':<10}")
    print(f"  {'─' * 5} {'─' * 40} {'─' * 10} {'─' * 10}")
    for sid, desc, rc, dur in resultados:
        estado = "✓ OK" if rc == 0 else "✗ FALLO"
        print(f"  {sid:<5} {desc[:40]:<40} {estado:<10} {formato_tiempo(dur):<10}")

    print()
    print("  Resultados detallados disponibles en:")
    print(f"    {RESULTADOS_DIR}")
    print()
    print("  Próximo paso: revisar los .md generados y consolidar las decisiones")
    print("  de diseño en docs/diagnostico_empirico.md (entrada de Fase 2).")
    print()


if __name__ == "__main__":
    main()