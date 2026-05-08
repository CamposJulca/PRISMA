#!/usr/bin/env python3
"""
Diagnóstico 02 — Tiempo de establecer conexiones

Objetivo:
    Medir cuánto cuesta establecer cada tipo de conexión (TCP + auth).
    Esto nos dice si vale la pena reutilizar conexiones (cuello LDAP) y si
    los timeouts actuales son razonables.

Qué hace:
    - Mide tiempo de conectar y desconectar a cada base de datos SQL Server.
    - Mide tiempo de hacer un bind a LDAP (sin búsqueda).
    - Reporta si alguna conexión está cerca de su timeout.

Uso:
    python diagnostics/02_tiempo_conexiones.py
"""

from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _utils import (
    Cronometro,
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


def medir_conexion_sql(nombre: str, server: str, db: str, user: str, password: str) -> dict:
    """Mide tiempo de conexión + ping + cierre a una BD SQL Server."""
    seccion(f"SQL Server — {nombre}")
    try:
        import pyodbc

        driver = "ODBC Driver 17 for SQL Server"
        conn_str = f"DRIVER={{{driver}}};SERVER={server};DATABASE={db};UID={user};PWD={password};"

        with Cronometro("Conectar") as t_conn:
            conn = pyodbc.connect(conn_str, timeout=30)

        with Cronometro("Ping (SELECT 1)") as t_ping:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.close()

        with Cronometro("Cerrar") as t_close:
            conn.close()

        ok(f"{nombre} alcanzable")
        return {
            "fuente": nombre,
            "conectar_s": t_conn.duracion,
            "ping_s": t_ping.duracion,
            "cerrar_s": t_close.duracion,
            "total_s": t_conn.duracion + t_ping.duracion + t_close.duracion,
            "ok": True,
        }
    except Exception as e:
        warn(f"No se pudo conectar: {e}")
        return {"fuente": nombre, "ok": False, "error": str(e)}


def medir_conexion_ldap() -> dict:
    """Mide tiempo de conectar + bind + close a LDAP."""
    seccion("LDAP / Active Directory")
    try:
        from ldap3 import ALL, SIMPLE, Connection, Server

        ldap_url = env("LDAP_SERVER")
        ldap_user = env("LDAP_USER")
        ldap_pwd = env("LDAP_PASSWORD")

        with Cronometro("Crear Server") as t_server:
            server = Server(ldap_url, get_info=ALL)

        with Cronometro("Conexión + bind") as t_bind:
            conn = Connection(
                server,
                user=ldap_user,
                password=ldap_pwd,
                authentication=SIMPLE,
                auto_bind=True,
                receive_timeout=10,
            )

        with Cronometro("Cerrar (unbind)") as t_close:
            conn.unbind()

        ok("LDAP alcanzable")
        return {
            "fuente": "LDAP / AD",
            "crear_server_s": t_server.duracion,
            "bind_s": t_bind.duracion,
            "cerrar_s": t_close.duracion,
            "total_s": t_server.duracion + t_bind.duracion + t_close.duracion,
            "ok": True,
        }
    except Exception as e:
        warn(f"No se pudo conectar a LDAP: {e}")
        return {"fuente": "LDAP / AD", "ok": False, "error": str(e)}


def main() -> None:
    header("Tiempo de establecer conexiones", "02")

    print("  Mide cuánto cuesta abrir cada conexión (TCP + auth + cierre).")
    print("  Útil para estimar el costo de NO reutilizar conexiones.")
    print()

    buffer_md = StringIO()
    buffer_md.write("# Diagnóstico 02 — Tiempo de establecer conexiones\n\n")

    resultados: list[dict] = []

    # SQL Aranda
    resultados.append(
        medir_conexion_sql(
            "Aranda ITSM",
            env("ARANDA_DB_SERVER"),
            env("ARANDA_DB_NAME"),
            env("ARANDA_DB_USER"),
            env("ARANDA_DB_PASSWORD"),
        )
    )

    # SQL Discovery
    resultados.append(
        medir_conexion_sql(
            "Aranda Discovery",
            env("DISCOVERY_DB_SERVER"),
            env("DISCOVERY_DB_NAME"),
            env("DISCOVERY_DB_USER"),
            env("DISCOVERY_DB_PASSWORD"),
        )
    )

    # SQL Kactus
    resultados.append(
        medir_conexion_sql(
            "Kactus",
            env("KACTUS_DB_SERVER"),
            env("KACTUS_DB_NAME"),
            env("KACTUS_DB_USER"),
            env("KACTUS_DB_PASSWORD"),
        )
    )

    # LDAP
    resultados.append(medir_conexion_ldap())

    # --- Resumen ---
    seccion("Resumen")
    buffer_md.write("## Resumen\n\n")
    buffer_md.write("| Fuente | Tiempo total | Conectar | Operación | Cerrar |\n")
    buffer_md.write("|---|---|---|---|---|\n")

    total_acumulado = 0.0
    for r in resultados:
        if r.get("ok"):
            metrica(
                r["fuente"],
                f"{formato_tiempo(r['total_s'])} (conectar: {formato_tiempo(r.get('conectar_s', r.get('bind_s', 0)))})",
            )
            total_acumulado += r["total_s"]
            conectar = r.get("conectar_s") or r.get("bind_s", 0)
            ping = r.get("ping_s", 0)
            cerrar = r.get("cerrar_s", 0)
            buffer_md.write(
                f"| {r['fuente']} | {formato_tiempo(r['total_s'])} | "
                f"{formato_tiempo(conectar)} | {formato_tiempo(ping)} | "
                f"{formato_tiempo(cerrar)} |\n"
            )
        else:
            metrica(r["fuente"], "FALLÓ")
            buffer_md.write(f"| {r['fuente']} | ❌ {r.get('error', '')[:60]} | - | - | - |\n")

    metrica("Suma de tiempos de todas las conexiones", formato_tiempo(total_acumulado))
    buffer_md.write(f"\n**Suma total:** {formato_tiempo(total_acumulado)}\n")

    # --- Conclusión basada en LDAP ---
    ldap_result = next((r for r in resultados if r["fuente"] == "LDAP / AD"), None)
    if ldap_result and ldap_result.get("ok"):
        bind_ms = ldap_result["bind_s"] * 1000
        veredicto_ldap = (
            f"Bind LDAP: {bind_ms:.1f} ms.\n"
        )
        if bind_ms > 100:
            veredicto_ldap += (
                "Es un costo ALTO. Si el notebook hace 200+ búsquedas con conexión\n"
                "nueva por iteración, eso es ~{:.0f} segundos solo en bind.\n".format(
                    bind_ms * 200 / 1000
                )
            )
        else:
            veredicto_ldap += (
                "Es un costo moderado. El cuello LDAP existe pero no es catastrófico.\n"
            )
    else:
        veredicto_ldap = "LDAP no se pudo medir.\n"

    conclusion(
        f"{veredicto_ldap}\n"
        f"Próximo paso: ejecutar 04_ldap_unitario.py y 05_ldap_batch.py para\n"
        f"medir empíricamente el costo de búsquedas reales con datos del proceso."
    )

    guardar_resultado("02_conexiones", buffer_md.getvalue())


if __name__ == "__main__":
    main()