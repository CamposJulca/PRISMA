#!/usr/bin/env python3
"""
Diagnóstico 03 — Tiempo de lectura de CSV y Excel

Objetivo:
    Medir cuánto tarda la lectura de cada archivo de entrada con pandas,
    y comparar el costo de Excel vs CSV. Esto nos dice si vale la pena
    pre-convertir los Excel a CSV/Parquet en alguna etapa.

Qué hace:
    - Lee cada archivo de data/raw/ midiendo tiempo.
    - Reporta tamaño en disco vs tiempo de lectura.
    - Identifica los archivos más costosos.

Uso:
    python diagnostics/03_tiempo_lectura_csv.py
"""

from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _utils import (
    Cronometro,
    PROJECT_ROOT,
    conclusion,
    env,
    formato_tiempo,
    guardar_resultado,
    header,
    metrica,
    ok,
    seccion,
    warn,
)


def medir_lectura(ruta: Path, separador: str = ",") -> dict:
    """Mide tiempo de lectura de un archivo CSV o Excel."""
    if not ruta.exists():
        return {"archivo": ruta.name, "ok": False, "error": "no existe"}

    try:
        import pandas as pd

        tamano_kb = ruta.stat().st_size / 1024

        if ruta.suffix == ".csv":
            with Cronometro() as t:
                df = pd.read_csv(ruta, sep=separador, low_memory=False)
        elif ruta.suffix in (".xlsx", ".xls"):
            with Cronometro() as t:
                df = pd.read_excel(ruta)
        else:
            return {"archivo": ruta.name, "ok": False, "error": "formato no soportado"}

        n_filas, n_cols = df.shape
        velocidad_mb_s = (tamano_kb / 1024) / t.duracion if t.duracion > 0 else 0

        metrica(
            f"  {ruta.name:<35}",
            f"{formato_tiempo(t.duracion):<12} ({n_filas:>7,} filas, {tamano_kb:>7.1f} KB)",
        )

        return {
            "archivo": ruta.name,
            "filas": n_filas,
            "columnas": n_cols,
            "tamano_kb": round(tamano_kb, 1),
            "tiempo_s": t.duracion,
            "velocidad_mb_s": round(velocidad_mb_s, 2),
            "ok": True,
        }
    except Exception as e:
        return {"archivo": ruta.name, "ok": False, "error": str(e)}


def main() -> None:
    header("Tiempo de lectura de archivos locales", "03")

    print("  Mide tiempo de pd.read_csv / pd.read_excel sobre cada archivo.")
    print("  Identifica cuáles son los más costosos y candidatos a pre-conversión.")
    print()

    buffer_md = StringIO()
    buffer_md.write("# Diagnóstico 03 — Tiempo de lectura de archivos\n\n")

    raw_dir = Path(env("DATA_RAW_DIR", "./data/raw", False))
    if not raw_dir.is_absolute():
        raw_dir = PROJECT_ROOT / raw_dir

    if not raw_dir.exists():
        warn(f"Directorio {raw_dir} no existe.")
        sys.exit(1)

    # Configuración: archivos esperados con su separador
    archivos = [
        ("usuarios.csv", ","),
        ("especialistas.csv", ","),
        ("GLPI.csv", ";"),  # GLPI usa ; según notebook
        ("GEUS.xlsx", None),
        ("Incidentes.csv", ","),
        ("Requerimientos.csv", ","),
        ("Cambios.csv", ","),
        ("Tareas.csv", ","),
        ("IncidentesStefanini.csv", ","),
        ("RequerimientosStefanini.csv", ","),
        ("ProblemasStefanini.csv", ","),
        ("CambiosStefanini.csv", ","),
    ]

    seccion("Lectura de cada archivo")
    resultados = []
    tiempo_total = 0.0
    for nombre, sep in archivos:
        ruta = raw_dir / nombre
        if not ruta.exists():
            warn(f"  {nombre:<35} no encontrado")
            continue
        r = medir_lectura(ruta, sep or ",")
        if r["ok"]:
            tiempo_total += r["tiempo_s"]
        resultados.append(r)

    # --- Resumen ---
    seccion("Resumen")
    metrica("Archivos leídos exitosamente", sum(1 for r in resultados if r.get("ok")))
    metrica("Tiempo total de lectura", formato_tiempo(tiempo_total))

    # Top 3 más lentos
    leidos_ok = [r for r in resultados if r.get("ok")]
    if leidos_ok:
        leidos_ok.sort(key=lambda x: x["tiempo_s"], reverse=True)
        print()
        print("  Top 3 archivos más costosos:")
        for r in leidos_ok[:3]:
            metrica(
                f"    {r['archivo']}",
                f"{formato_tiempo(r['tiempo_s'])} ({r['filas']:,} filas)",
            )

    # Construir markdown
    buffer_md.write("## Resultados\n\n")
    buffer_md.write("| Archivo | Filas | Tamaño | Tiempo lectura | Velocidad |\n")
    buffer_md.write("|---|---|---|---|---|\n")
    for r in resultados:
        if r.get("ok"):
            buffer_md.write(
                f"| {r['archivo']} | {r['filas']:,} | {r['tamano_kb']:.1f} KB | "
                f"{formato_tiempo(r['tiempo_s'])} | {r['velocidad_mb_s']:.2f} MB/s |\n"
            )
        else:
            buffer_md.write(f"| {r['archivo']} | - | - | ❌ | {r.get('error', '')[:50]} |\n")

    buffer_md.write(f"\n**Tiempo total de lectura:** {formato_tiempo(tiempo_total)}\n")

    # Veredicto
    veredicto = (
        f"Tiempo total de lectura de archivos: {formato_tiempo(tiempo_total)}.\n"
    )
    if tiempo_total > 30:
        veredicto += (
            "Es un componente significativo del tiempo total. Vale la pena considerar:\n"
            "- Pre-convertir archivos Excel a Parquet (5-20x más rápido).\n"
            "- Cachear lecturas que no cambian entre corridas.\n"
        )
    else:
        veredicto += "No es un cuello de botella mayor por ahora.\n"

    conclusion(
        f"{veredicto}\n"
        f"Próximo paso: ejecutar 07_excel_vs_parquet.py para medir cuánto se gana\n"
        f"migrando intermedios a Parquet."
    )

    guardar_resultado("03_lectura_archivos", buffer_md.getvalue())


if __name__ == "__main__":
    main()