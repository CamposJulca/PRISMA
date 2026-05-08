#!/usr/bin/env python3
"""
Diagnóstico 05 — LDAP en batch vs conexión por iteración (EXPERIMENTO CLAVE)

Objetivo:
    Validar empíricamente la hipótesis principal de la Fase 1:
    que abrir/cerrar la conexión LDAP por cada búsqueda es el cuello de
    botella #1, y que una conexión persistente con búsquedas batch lo elimina.

    Este es el script más importante de la batería de diagnóstico — su
    resultado determina si el rediseño del módulo LDAP debe ser PRIORITARIO.

Qué hace:
    Ejecuta 3 estrategias sobre el mismo conjunto de N cédulas:
      A) Patrón actual (notebook): conexión nueva por cada búsqueda.
      B) Conexión persistente: una sola conexión, múltiples búsquedas.
      C) Búsqueda batch con filtro OR: una conexión, una sola búsqueda
         con filtro `(|(employeeID=X)(employeeID=Y)...)`.

    Compara tiempos y reporta speedup.

Importante:
    Solo lectura LDAP, ningún side effect.

Uso:
    python diagnostics/05_ldap_batch.py [N]

    N = cantidad de cédulas a usar para la prueba (default 30).
    Si se quieren cédulas reales, editar la variable CEDULAS_REALES o pasar
    cédulas como variables de entorno.
"""

from __future__ import annotations

import statistics
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

# --- Configuración del experimento ---
N_DEFAULT = 30  # Cuántas cédulas usar


def estrategia_a_actual(cedulas: list[str]) -> tuple[float, dict]:
    """
    A) Patrón actual del notebook: conexión nueva por iteración.
    Retorna (duracion_total, dict de resultados {cedula: username}).
    """
    from ldap3 import SIMPLE, Connection, Server

    server_address = env("LDAP_SERVER")
    base_dn = env("LDAP_BASE_DN")
    user = env("LDAP_USER")
    password = env("LDAP_PASSWORD")

    resultados: dict = {}

    with Cronometro() as t:
        for cedula in cedulas:
            try:
                server = Server(server_address)
                with Connection(
                    server, user=user, password=password, authentication=SIMPLE,
                    raise_exceptions=False,
                ) as conn:
                    conn.bind()
                    conn.search(
                        search_base=base_dn,
                        search_filter=f"(&(objectClass=user)(employeeID={cedula}))",
                        search_scope="SUBTREE",
                        attributes=["sAMAccountName"],
                    )
                    for entry in conn.entries:
                        if "sAMAccountName" in entry:
                            resultados[cedula] = entry.sAMAccountName.value
            except Exception:
                pass

    return t.duracion, resultados


def estrategia_b_persistente(cedulas: list[str]) -> tuple[float, dict]:
    """
    B) Conexión persistente: una sola conexión, múltiples búsquedas.
    """
    from ldap3 import SIMPLE, Connection, Server

    server_address = env("LDAP_SERVER")
    base_dn = env("LDAP_BASE_DN")
    user = env("LDAP_USER")
    password = env("LDAP_PASSWORD")

    resultados: dict = {}

    with Cronometro() as t:
        server = Server(server_address)
        conn = Connection(
            server, user=user, password=password, authentication=SIMPLE,
            auto_bind=True, raise_exceptions=False,
        )
        try:
            for cedula in cedulas:
                conn.search(
                    search_base=base_dn,
                    search_filter=f"(&(objectClass=user)(employeeID={cedula}))",
                    search_scope="SUBTREE",
                    attributes=["sAMAccountName"],
                )
                for entry in conn.entries:
                    if "sAMAccountName" in entry:
                        resultados[cedula] = entry.sAMAccountName.value
        finally:
            conn.unbind()

    return t.duracion, resultados


def estrategia_c_batch(cedulas: list[str], chunk_size: int = 50) -> tuple[float, dict]:
    """
    C) Búsqueda batch con filtro OR: agrupa cédulas en chunks y hace una
    búsqueda por chunk con filtro (|(employeeID=X)(employeeID=Y)...).
    """
    from ldap3 import SIMPLE, Connection, Server

    server_address = env("LDAP_SERVER")
    base_dn = env("LDAP_BASE_DN")
    user = env("LDAP_USER")
    password = env("LDAP_PASSWORD")

    resultados: dict = {}

    with Cronometro() as t:
        server = Server(server_address)
        conn = Connection(
            server, user=user, password=password, authentication=SIMPLE,
            auto_bind=True, raise_exceptions=False,
        )
        try:
            for inicio in range(0, len(cedulas), chunk_size):
                chunk = cedulas[inicio : inicio + chunk_size]
                # Construir filtro OR
                filtros_or = "".join(f"(employeeID={c})" for c in chunk)
                search_filter = f"(&(objectClass=user)(|{filtros_or}))"

                conn.search(
                    search_base=base_dn,
                    search_filter=search_filter,
                    search_scope="SUBTREE",
                    attributes=["sAMAccountName", "employeeID"],
                )
                for entry in conn.entries:
                    if "employeeID" in entry and "sAMAccountName" in entry:
                        ced = str(entry.employeeID.value)
                        resultados[ced] = entry.sAMAccountName.value
        finally:
            conn.unbind()

    return t.duracion, resultados


def main() -> None:
    header("LDAP batch vs conexión por iteración (experimento clave)", "05")

    print("  Compara 3 estrategias sobre las mismas N cédulas:")
    print("    A) Conexión nueva por iteración (patrón actual del notebook)")
    print("    B) Conexión persistente con N búsquedas")
    print("    C) Conexión persistente con búsqueda batch (filtro OR)")
    print()

    # Argumento N
    n = int(sys.argv[1]) if len(sys.argv) > 1 else N_DEFAULT

    buffer_md = StringIO()
    buffer_md.write("# Diagnóstico 05 — LDAP batch vs por iteración\n\n")

    # Generar cédulas de prueba: rango numérico ficticio.
    # Las búsquedas no encontrarán resultados reales, pero el costo de la
    # operación de red se mide igualmente. Para mediciones más representativas,
    # se puede modificar este bloque para tomar cédulas reales del SP de Discovery.
    cedulas = [str(1000000 + i * 7) for i in range(n)]

    seccion(f"Configuración del experimento")
    metrica("Cantidad de cédulas a buscar", n)
    metrica("Tipo de cédulas", "ficticias (sólo medimos costo de red, no resultados)")

    print()
    print("  ⚠  Para una medición más realista con cédulas que existen en AD,")
    print("     ejecutar primero 01_volumetria_fuentes.py y extraer cédulas reales")
    print("     del SP de Discovery, luego pasarlas modificando este script.")
    print()

    # --- Ejecutar las 3 estrategias ---
    seccion("Ejecutando estrategia A — conexión nueva por iteración")
    try:
        t_a, r_a = estrategia_a_actual(cedulas)
        ok(f"A completada en {formato_tiempo(t_a)} — {len(r_a)} resultados encontrados")
    except Exception as e:
        warn(f"A falló: {e}")
        t_a, r_a = float("inf"), {}

    seccion("Ejecutando estrategia B — conexión persistente")
    try:
        t_b, r_b = estrategia_b_persistente(cedulas)
        ok(f"B completada en {formato_tiempo(t_b)} — {len(r_b)} resultados encontrados")
    except Exception as e:
        warn(f"B falló: {e}")
        t_b, r_b = float("inf"), {}

    seccion("Ejecutando estrategia C — búsqueda batch con filtro OR")
    try:
        t_c, r_c = estrategia_c_batch(cedulas)
        ok(f"C completada en {formato_tiempo(t_c)} — {len(r_c)} resultados encontrados")
    except Exception as e:
        warn(f"C falló: {e}")
        t_c, r_c = float("inf"), {}

    # --- Resumen comparativo ---
    seccion("Resumen comparativo")
    metrica("A) Conexión por iteración (patrón actual)", formato_tiempo(t_a))
    metrica("B) Conexión persistente", formato_tiempo(t_b))
    metrica("C) Búsqueda batch", formato_tiempo(t_c))

    print()
    if t_a > 0 and t_b < float("inf"):
        speedup_b = t_a / t_b if t_b > 0 else 0
        ahorro_b = (1 - t_b / t_a) * 100 if t_a > 0 else 0
        metrica("Speedup A→B (persistente vs actual)", f"{speedup_b:.1f}x")
        metrica("  Ahorro porcentual", f"{ahorro_b:.1f}%")

    if t_a > 0 and t_c < float("inf"):
        speedup_c = t_a / t_c if t_c > 0 else 0
        ahorro_c = (1 - t_c / t_a) * 100 if t_a > 0 else 0
        metrica("Speedup A→C (batch vs actual)", f"{speedup_c:.1f}x")
        metrica("  Ahorro porcentual", f"{ahorro_c:.1f}%")

    # Construir markdown
    buffer_md.write(f"## Configuración\n\n- N cédulas: {n}\n\n")
    buffer_md.write("## Tiempos\n\n")
    buffer_md.write("| Estrategia | Tiempo |\n|---|---|\n")
    buffer_md.write(f"| A — conexión por iteración (patrón actual) | {formato_tiempo(t_a)} |\n")
    buffer_md.write(f"| B — conexión persistente | {formato_tiempo(t_b)} |\n")
    buffer_md.write(f"| C — búsqueda batch | {formato_tiempo(t_c)} |\n\n")
    if t_a > 0:
        buffer_md.write(f"**Speedup A→B:** {t_a / t_b:.1f}x\n")
        buffer_md.write(f"**Speedup A→C:** {t_a / t_c:.1f}x\n")

    # Veredicto
    if t_a > 0 and t_c > 0:
        speedup = t_a / t_c
        if speedup > 5:
            veredicto = (
                f"Speedup de {speedup:.1f}x con búsqueda batch.\n"
                f"La hipótesis del cuello LDAP queda CONFIRMADA empíricamente.\n"
                f"Implementar el cliente LDAP persistente con batch es PRIORIDAD ALTA\n"
                f"para el módulo identity/ldap_cache.py.\n"
            )
        elif speedup > 2:
            veredicto = (
                f"Speedup de {speedup:.1f}x con búsqueda batch.\n"
                f"Hay ganancia clara pero no espectacular. Vale la pena implementarlo,\n"
                f"pero el cuello LDAP no domina los 7m11s totales.\n"
            )
        else:
            veredicto = (
                f"Speedup de solo {speedup:.1f}x con búsqueda batch.\n"
                f"El LDAP NO es el cuello de botella principal en esta red/configuración.\n"
                f"Priorizar la optimización de iterrows() y otros patrones.\n"
            )
    else:
        veredicto = "No se pudieron medir tiempos válidos. Revisar conectividad LDAP.\n"

    conclusion(
        f"{veredicto}\n"
        f"Próximo paso: ejecutar 06_iterrows_vs_vectorizado.py para medir el otro\n"
        f"gran cuello identificado en el diagnóstico estático."
    )

    guardar_resultado("05_ldap_batch", buffer_md.getvalue())


if __name__ == "__main__":
    main()