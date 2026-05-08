#!/usr/bin/env python3
"""
Diagnóstico 01 — Volumetría de fuentes

Objetivo:
    Conocer el tamaño real de cada fuente de datos del proceso, antes de medir
    tiempos. Estos números informan cómo interpretar los resultados de los
    scripts siguientes y son insumo directo para decisiones como:
      - ¿Vale la pena la carga incremental sobre los SP?
      - ¿Cuántas búsquedas LDAP se necesitan en una corrida típica?
      - ¿Qué % de los casos vienen de cada origen?

Qué hace:
    - Cuenta filas de cada SP de SQL (Aranda Discovery, Aranda ITSM, Kactus).
    - Cuenta filas de cada CSV/Excel de entrada.
    - Reporta cuántas cédulas únicas necesitan resolución (insumo para script 04).
    - NO transforma ni escribe nada.

Uso:
    python diagnostics/01_volumetria_fuentes.py
"""

from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path

# Agregar la raíz al path para poder importar _utils
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _utils import (
    Cronometro,
    PROJECT_ROOT,
    conclusion,
    env,
    error,
    formato_tiempo,
    guardar_resultado,
    header,
    metrica,
    ok,
    seccion,
    warn,
)


def medir_sql_aranda_discovery() -> dict:
    """Mide volumetría del SP de Aranda Discovery (SP_CASOS_DISCOVERYGTI_V1)."""
    seccion("Aranda Discovery (SP_CASOS_DISCOVERYGTI_V1)")
    try:
        import pyodbc

        conn_str = (
            f"DRIVER={{{env('DISCOVERY_DB_DRIVER', 'ODBC Driver 17 for SQL Server')}}};"
            f"SERVER={env('DISCOVERY_DB_SERVER')};"
            f"DATABASE={env('DISCOVERY_DB_NAME')};"
            f"UID={env('DISCOVERY_DB_USER')};"
            f"PWD={env('DISCOVERY_DB_PASSWORD')};"
        )

        with Cronometro("Conexión") as t_conn:
            conn = pyodbc.connect(conn_str, timeout=int(env("DB_CONNECTION_TIMEOUT", "30", False)))

        with Cronometro("Ejecución SP") as t_sp:
            cursor = conn.cursor()
            cursor.execute("EXEC SP_CASOS_DISCOVERYGTI_V1")
            filas = cursor.fetchall()
            n_filas = len(filas)
            n_cols = len(cursor.description) if cursor.description else 0

        # Contar cédulas (campos username_ufinal que son sólo dígitos)
        cedulas_unicas: set[str] = set()
        idx_username = next(
            (i for i, col in enumerate(cursor.description) if col[0] == "username_ufinal"),
            None,
        )
        if idx_username is not None:
            for fila in filas:
                valor = fila[idx_username]
                if valor and str(valor).isdigit():
                    cedulas_unicas.add(str(valor))

        cursor.close()
        conn.close()

        metrica("Filas retornadas", f"{n_filas:,}")
        metrica("Columnas", n_cols)
        metrica("Cédulas únicas a resolver vía LDAP", f"{len(cedulas_unicas):,}")
        ok("Lectura completada")

        return {
            "fuente": "Aranda Discovery (SP)",
            "filas": n_filas,
            "columnas": n_cols,
            "cedulas_unicas": len(cedulas_unicas),
            "tiempo_conexion_s": t_conn.duracion,
            "tiempo_ejecucion_s": t_sp.duracion,
            "ok": True,
        }
    except Exception as e:
        warn(f"No se pudo medir: {e}")
        return {"fuente": "Aranda Discovery (SP)", "ok": False, "error": str(e)}


def medir_sql_aranda_itsm() -> list[dict]:
    """Mide volumetría de los 3 SPs de Aranda ITSM."""
    seccion("Aranda ITSM (SP_INCIDENTESGTI1, SP_SERVICECALL1, SP_CHANGES1)")
    resultados = []
    try:
        import pyodbc

        conn_str = (
            f"DRIVER={{{env('ARANDA_DB_DRIVER', 'ODBC Driver 17 for SQL Server')}}};"
            f"SERVER={env('ARANDA_DB_SERVER')};"
            f"DATABASE={env('ARANDA_DB_NAME')};"
            f"UID={env('ARANDA_DB_USER')};"
            f"PWD={env('ARANDA_DB_PASSWORD')};"
        )

        with Cronometro("Conexión") as t_conn:
            conn = pyodbc.connect(conn_str, timeout=int(env("DB_CONNECTION_TIMEOUT", "30", False)))

        for sp in ["SP_INCIDENTESGTI1", "SP_SERVICECALL1", "SP_CHANGES1"]:
            try:
                with Cronometro(f"Ejecución {sp}") as t_sp:
                    cursor = conn.cursor()
                    cursor.execute(f"EXEC {sp}")
                    filas = cursor.fetchall()
                    n_filas = len(filas)
                    n_cols = len(cursor.description) if cursor.description else 0
                    cursor.close()

                metrica(f"  {sp} — filas", f"{n_filas:,}")
                resultados.append({
                    "fuente": f"Aranda ITSM ({sp})",
                    "filas": n_filas,
                    "columnas": n_cols,
                    "tiempo_ejecucion_s": t_sp.duracion,
                    "ok": True,
                })
            except Exception as e:
                warn(f"  {sp} falló: {e}")
                resultados.append({"fuente": f"Aranda ITSM ({sp})", "ok": False, "error": str(e)})

        conn.close()
    except Exception as e:
        warn(f"No se pudo conectar a Aranda ITSM: {e}")
        resultados.append({"fuente": "Aranda ITSM", "ok": False, "error": str(e)})

    return resultados


def medir_sql_kactus() -> dict:
    """Mide volumetría de la consulta de Kactus."""
    seccion("Kactus (consulta de empleados)")
    try:
        import pyodbc

        conn_str = (
            f"DRIVER={{{env('KACTUS_DB_DRIVER', 'ODBC Driver 17 for SQL Server')}}};"
            f"SERVER={env('KACTUS_DB_SERVER')};"
            f"DATABASE={env('KACTUS_DB_NAME')};"
            f"UID={env('KACTUS_DB_USER')};"
            f"PWD={env('KACTUS_DB_PASSWORD')};"
        )

        query = (
            "select distinct RTRIM(emp.nom_empl) + ' ' + RTRIM(emp.ape_empl) as NombreCompleto, "
            "cast(emp.cod_empl as varchar(50)) as cedula, "
            "case when CHARINDEX('@', emp.box_mail) > 0 "
            "then left(emp.box_mail, CHARINDEX('@', emp.box_mail) -1) else emp.box_mail end as username "
            "from gn_accaj gn inner join bi_emple emp on gn.COD_EMPL = emp.cod_empl "
            "where CHARINDEX('@', emp.box_mail) > 0 order by NombreCompleto"
        )

        with Cronometro("Conexión") as t_conn:
            conn = pyodbc.connect(conn_str, timeout=int(env("DB_CONNECTION_TIMEOUT", "30", False)))

        with Cronometro("Ejecución query") as t_q:
            cursor = conn.cursor()
            cursor.execute(query)
            filas = cursor.fetchall()
            n_filas = len(filas)
            cursor.close()

        conn.close()

        metrica("Empleados retornados", f"{n_filas:,}")
        ok("Lectura completada")

        return {
            "fuente": "Kactus (consulta empleados)",
            "filas": n_filas,
            "tiempo_conexion_s": t_conn.duracion,
            "tiempo_ejecucion_s": t_q.duracion,
            "ok": True,
        }
    except Exception as e:
        warn(f"No se pudo medir: {e}")
        return {"fuente": "Kactus", "ok": False, "error": str(e)}


def medir_archivos_locales() -> list[dict]:
    """Mide volumetría de los archivos CSV y Excel de entrada."""
    seccion("Archivos locales (CSV y Excel)")
    raw_dir = Path(env("DATA_RAW_DIR", "./data/raw", False))
    if not raw_dir.is_absolute():
        raw_dir = PROJECT_ROOT / raw_dir

    if not raw_dir.exists():
        warn(f"Directorio {raw_dir} no existe. Crear y poner los CSVs ahí.")
        return []

    archivos_esperados = [
        ("usuarios.csv", "Diccionario usuarios"),
        ("especialistas.csv", "Diccionario especialistas"),
        ("GLPI.csv", "GLPI"),
        ("GEUS.xlsx", "GEUS"),
        ("Incidentes.csv", "Aranda ASMS - Incidentes"),
        ("Requerimientos.csv", "Aranda ASMS - Requerimientos"),
        ("Cambios.csv", "Aranda ASMS - Cambios"),
        ("Tareas.csv", "Aranda ASMS - Tareas"),
        ("IncidentesStefanini.csv", "Stefanini - Incidentes"),
        ("RequerimientosStefanini.csv", "Stefanini - Requerimientos"),
        ("ProblemasStefanini.csv", "Stefanini - Problemas"),
        ("CambiosStefanini.csv", "Stefanini - Cambios"),
    ]

    resultados = []
    for nombre, descripcion in archivos_esperados:
        ruta = raw_dir / nombre
        if not ruta.exists():
            warn(f"  {nombre:<35} no encontrado en {raw_dir}")
            continue

        tamano_kb = ruta.stat().st_size / 1024
        # Conteo rápido de líneas para CSVs
        if ruta.suffix == ".csv":
            try:
                with ruta.open("r", encoding="utf-8", errors="replace") as f:
                    n_lineas = sum(1 for _ in f) - 1  # -1 por el header
            except Exception:
                n_lineas = -1
            metrica(f"  {nombre:<35}", f"{n_lineas:>7,} filas  ({tamano_kb:>7.1f} KB)")
            resultados.append({
                "fuente": f"{descripcion} ({nombre})",
                "filas": n_lineas,
                "tamano_kb": round(tamano_kb, 1),
                "ok": True,
            })
        elif ruta.suffix in (".xlsx", ".xls"):
            try:
                import pandas as pd

                df = pd.read_excel(ruta)
                n_filas = len(df)
            except Exception:
                n_filas = -1
            metrica(f"  {nombre:<35}", f"{n_filas:>7,} filas  ({tamano_kb:>7.1f} KB)")
            resultados.append({
                "fuente": f"{descripcion} ({nombre})",
                "filas": n_filas,
                "tamano_kb": round(tamano_kb, 1),
                "ok": True,
            })

    return resultados


def main() -> None:
    header("Volumetría de fuentes de datos", "01")

    print("  Este script consulta el tamaño de cada fuente sin transformar nada.")
    print("  Los resultados informan cómo interpretar los scripts siguientes.")
    print()

    # Capturar todo el output también para guardarlo
    buffer_md = StringIO()
    buffer_md.write("# Diagnóstico 01 — Volumetría de fuentes\n\n")

    todos_los_resultados: list[dict] = []

    # --- SQL ---
    r1 = medir_sql_aranda_discovery()
    todos_los_resultados.append(r1)

    r2_lista = medir_sql_aranda_itsm()
    todos_los_resultados.extend(r2_lista)

    r3 = medir_sql_kactus()
    todos_los_resultados.append(r3)

    # --- Archivos ---
    r4_lista = medir_archivos_locales()
    todos_los_resultados.extend(r4_lista)

    # --- Resumen ---
    seccion("Resumen consolidado")
    total_filas = 0
    fuentes_ok = 0
    for r in todos_los_resultados:
        if r.get("ok"):
            fuentes_ok += 1
            total_filas += r.get("filas", 0) or 0

    metrica("Fuentes consultadas con éxito", f"{fuentes_ok} / {len(todos_los_resultados)}")
    metrica("Total aproximado de filas a procesar", f"{total_filas:,}")

    cedulas = next(
        (r.get("cedulas_unicas", 0) for r in todos_los_resultados if "cedulas_unicas" in r),
        0,
    )
    if cedulas:
        metrica("Cédulas únicas que necesitan LDAP", f"{cedulas:,}")

    # Construir markdown
    buffer_md.write("## Resultados por fuente\n\n")
    buffer_md.write("| Fuente | Filas | Estado |\n")
    buffer_md.write("|---|---|---|\n")
    for r in todos_los_resultados:
        if r.get("ok"):
            buffer_md.write(f"| {r['fuente']} | {r.get('filas', 'N/A'):,} | ✅ |\n")
        else:
            buffer_md.write(f"| {r['fuente']} | - | ❌ {r.get('error', '')[:80]} |\n")

    buffer_md.write(f"\n**Total filas:** {total_filas:,}\n")
    buffer_md.write(f"**Cédulas únicas a resolver vía LDAP:** {cedulas:,}\n")

    conclusion(
        f"Procesando ~{total_filas:,} filas en total entre todas las fuentes.\n"
        f"Cédulas que necesitan LDAP: {cedulas:,}.\n"
        f"Si este número de cédulas es alto (>500), el cuello LDAP es severo.\n"
        f"Si es bajo (<100), el problema dominante es probablemente otro.\n"
        f"\n"
        f"Próximo paso: ejecutar 02_tiempo_conexiones.py para medir latencia\n"
        f"de conexión, y luego 04_ldap_unitario.py para medir el costo por búsqueda."
    )

    guardar_resultado("01_volumetria", buffer_md.getvalue())


if __name__ == "__main__":
    main()