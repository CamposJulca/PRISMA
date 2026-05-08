#!/usr/bin/env python3
"""
Diagnóstico 07 — Excel vs Parquet vs CSV

Objetivo:
    Medir cuánto tiempo se ahorra migrando los archivos intermedios de Excel
    a Parquet (formato binario columnar). Las escrituras intermedias del
    notebook fueron identificadas como cuello #3 en el diagnóstico estático.

Qué hace:
    Sobre un DataFrame sintético del tamaño de indicators1.xlsx (~63K filas),
    mide tiempo y tamaño de:
      - Escritura .xlsx (openpyxl)
      - Escritura .csv
      - Escritura .parquet
    Y luego compara también las lecturas.

    Reporta tiempos absolutos, ratios y tamaños en disco.

Importante:
    Los archivos se escriben en /tmp y se eliminan al terminar.

Uso:
    python diagnostics/07_excel_vs_parquet.py [N]

    N = filas del dataframe sintético (default 60000, similar a indicators1).
"""

from __future__ import annotations

import sys
import tempfile
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _utils import (
    Cronometro,
    conclusion,
    formato_tiempo,
    guardar_resultado,
    header,
    metrica,
    ok,
    seccion,
    warn,
)


def generar_dataframe_realista(n: int):
    """
    Genera un DataFrame con la forma y tipos de columnas similares a
    indicators1.xlsx (15 columnas, mix de strings, int, datetime).
    """
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(42)
    inicio = pd.Timestamp("2020-01-01")

    df = pd.DataFrame({
        "tipo_de_caso": rng.choice(["Incidente", "Requerimiento", "Cambio", "Tarea"], size=n),
        "origen_caso": rng.choice(["Discovery", "Aranda ASMS", "GLPI", "GEUS"], size=n),
        "proyecto": rng.choice(["Soporte", "Mesa de Software", "Mesa de Servicios"], size=n),
        "numero_caso": rng.integers(1, 100000, size=n),
        "servicio": rng.choice(
            ["AGROS", "FAG SERVICIOS", "Office 365", "Buzón Seguro", "SARLAFT"], size=n
        ),
        "responsable": [f"responsable_{i % 200}" for i in range(n)],
        "username_resp": [f"resp{i % 200}" for i in range(n)],
        "usuariofinal": [f"Usuario Apellido {i % 500}" for i in range(n)],
        "username_ufinal": [f"user{i % 500}" for i in range(n)],
        "fecha_creacion": [inicio + pd.Timedelta(minutes=int(rng.integers(0, 2_000_000))) for _ in range(n)],
        "fecha_atencion": [inicio + pd.Timedelta(minutes=int(rng.integers(0, 2_000_000))) for _ in range(n)],
        "fecha_solucion": [inicio + pd.Timedelta(minutes=int(rng.integers(0, 2_000_000))) for _ in range(n)],
        "tiempoTranscurrido": rng.integers(1, 10000, size=n),
        "CUMPLE_ANS": rng.choice(["SI", "NO"], size=n),
        "extra": [f"valor_{i}" for i in range(n)],
    })

    return df


def main() -> None:
    header("Excel vs Parquet vs CSV", "07")

    print("  Mide escritura y lectura de los 3 formatos sobre un DataFrame")
    print("  del tamaño de indicators1.xlsx para evaluar la ganancia de migrar.")
    print()

    n = int(sys.argv[1]) if len(sys.argv) > 1 else 60000

    buffer_md = StringIO()
    buffer_md.write("# Diagnóstico 07 — Excel vs Parquet vs CSV\n\n")

    seccion("Configuración")
    metrica("Filas del DataFrame sintético", f"{n:,}")

    seccion("Generando DataFrame")
    df = generar_dataframe_realista(n)
    metrica("Forma del DataFrame", f"{df.shape[0]:,} × {df.shape[1]}")
    metrica("Memoria (estimada)", f"{df.memory_usage(deep=True).sum() / 1024 / 1024:.1f} MB")

    # Carpeta temporal
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # --- Escritura ---
        seccion("Escritura — tiempo y tamaño en disco")

        # Excel
        ruta_xlsx = tmp / "test.xlsx"
        with Cronometro() as t_w_xlsx:
            df.to_excel(ruta_xlsx, index=False)
        size_xlsx = ruta_xlsx.stat().st_size / 1024
        metrica("  .xlsx — escritura", f"{formato_tiempo(t_w_xlsx.duracion)}  ({size_xlsx:.1f} KB)")

        # CSV
        ruta_csv = tmp / "test.csv"
        with Cronometro() as t_w_csv:
            df.to_csv(ruta_csv, index=False)
        size_csv = ruta_csv.stat().st_size / 1024
        metrica("  .csv  — escritura", f"{formato_tiempo(t_w_csv.duracion)}  ({size_csv:.1f} KB)")

        # Parquet
        try:
            ruta_pq = tmp / "test.parquet"
            with Cronometro() as t_w_pq:
                df.to_parquet(ruta_pq, index=False)
            size_pq = ruta_pq.stat().st_size / 1024
            metrica("  .parquet — escritura", f"{formato_tiempo(t_w_pq.duracion)}  ({size_pq:.1f} KB)")
            parquet_ok = True
        except Exception as e:
            warn(f"  Parquet no disponible: {e}. Instalar pyarrow.")
            t_w_pq = None
            size_pq = 0
            parquet_ok = False

        # --- Lectura ---
        seccion("Lectura — tiempo")

        import pandas as pd

        with Cronometro() as t_r_xlsx:
            _ = pd.read_excel(ruta_xlsx)
        metrica("  .xlsx — lectura", formato_tiempo(t_r_xlsx.duracion))

        with Cronometro() as t_r_csv:
            _ = pd.read_csv(ruta_csv)
        metrica("  .csv  — lectura", formato_tiempo(t_r_csv.duracion))

        if parquet_ok:
            with Cronometro() as t_r_pq:
                _ = pd.read_parquet(ruta_pq)
            metrica("  .parquet — lectura", formato_tiempo(t_r_pq.duracion))

        # --- Resumen ---
        seccion("Resumen comparativo")

        # Speedup en escritura
        if t_w_xlsx.duracion > 0:
            speedup_csv = t_w_xlsx.duracion / t_w_csv.duracion if t_w_csv.duracion > 0 else 0
            metrica("Excel → CSV (escritura)", f"{speedup_csv:.1f}x más rápido")

            if parquet_ok and t_w_pq.duracion > 0:
                speedup_pq = t_w_xlsx.duracion / t_w_pq.duracion
                metrica("Excel → Parquet (escritura)", f"{speedup_pq:.1f}x más rápido")

        # Tamaño
        print()
        if size_xlsx > 0:
            metrica("Reducción tamaño Excel→CSV", f"{(1 - size_csv/size_xlsx)*100:.0f}%")
            if parquet_ok:
                metrica("Reducción tamaño Excel→Parquet", f"{(1 - size_pq/size_xlsx)*100:.0f}%")

        # Markdown
        buffer_md.write("## Resultados\n\n")
        buffer_md.write("### Escritura\n\n")
        buffer_md.write("| Formato | Tiempo | Tamaño |\n|---|---|---|\n")
        buffer_md.write(f"| .xlsx | {formato_tiempo(t_w_xlsx.duracion)} | {size_xlsx:.1f} KB |\n")
        buffer_md.write(f"| .csv | {formato_tiempo(t_w_csv.duracion)} | {size_csv:.1f} KB |\n")
        if parquet_ok:
            buffer_md.write(f"| .parquet | {formato_tiempo(t_w_pq.duracion)} | {size_pq:.1f} KB |\n")

        buffer_md.write("\n### Lectura\n\n")
        buffer_md.write("| Formato | Tiempo |\n|---|---|\n")
        buffer_md.write(f"| .xlsx | {formato_tiempo(t_r_xlsx.duracion)} |\n")
        buffer_md.write(f"| .csv | {formato_tiempo(t_r_csv.duracion)} |\n")
        if parquet_ok:
            buffer_md.write(f"| .parquet | {formato_tiempo(t_r_pq.duracion)} |\n")

        # Veredicto
        if parquet_ok and t_w_xlsx.duracion > 0 and t_w_pq.duracion > 0:
            speedup = t_w_xlsx.duracion / t_w_pq.duracion
            ahorro_estimado = (t_w_xlsx.duracion - t_w_pq.duracion) * 20  # ~20 escrituras intermedias
            veredicto = (
                f"Excel → Parquet: {speedup:.1f}x más rápido en escritura.\n"
                f"\n"
                f"Notebook actual hace ~25 escrituras intermedias a Excel.\n"
                f"Si la mayoría se migra a Parquet (uso interno) y solo las 3 finales\n"
                f"siguen en Excel (consumo de Power BI), el ahorro estimado por\n"
                f"corrida es de ~{formato_tiempo(ahorro_estimado)}.\n"
                f"\n"
                f"Recomendación: migrar intermedios a Parquet, mantener finales en Excel.\n"
            )
        else:
            veredicto = (
                f"CSV es {t_w_xlsx.duracion / t_w_csv.duracion:.1f}x más rápido que Excel.\n"
                f"Si pyarrow está disponible, Parquet sería aún mejor.\n"
            )

        conclusion(
            f"{veredicto}\n"
            f"Próximo paso: ejecutar 08_perfil_kactus.py para entender qué % de\n"
            f"identidades realmente necesita LDAP vs cuántas se resuelven con Kactus."
        )

    guardar_resultado("07_excel_vs_parquet", buffer_md.getvalue())


if __name__ == "__main__":
    main()