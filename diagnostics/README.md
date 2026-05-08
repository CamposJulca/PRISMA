# Diagnostics — exploración empírica previa a Fase 2

Esta carpeta contiene scripts de **exploración y medición** que se ejecutan **antes** de iniciar la Fase 2 (diseño detallado del refactor). Su propósito es validar empíricamente las hipótesis del diagnóstico estático de la Fase 1 y obtener números concretos para tomar decisiones de diseño basadas en evidencia.

---

## Diferencia con `scripts/`

| Carpeta | Propósito | Permanencia |
|---|---|---|
| `scripts/` | Utilidades operacionales del proyecto (profiling completo, comparación de outputs, etc.) | Permanente — se mantienen y evolucionan con el proyecto. |
| `diagnostics/` | Scripts de exploración puntual para tomar decisiones de diseño. | Conservadas como evidencia histórica, no se ejecutan en operación normal. |

---

## Principios de diseño de estos scripts

1. **Una sola cosa por script.** Cada uno mide o explora un único aspecto.
2. **Solo lectura.** Ningún script transforma datos ni escribe archivos en producción. La única escritura permitida es a `diagnostics/resultados/` con la evidencia formateada.
3. **Salida legible.** Se imprime a terminal con títulos, métricas claras, y conclusiones tentativas.
4. **Independientes.** Cada uno puede correr de forma aislada. No hay dependencias entre scripts.
5. **Cero riesgo.** No se conectan a sistemas de escritura, no usan `INSERT/UPDATE/DELETE`.

---

## Requisitos previos

```bash
# Desde la raíz del proyecto
source .venv/bin/activate
pip install -e ".[dev]"

# Configurar credenciales (ver .env.example)
cp .env.example .env
# Editar .env con las credenciales reales
```

Los scripts leen el `.env` automáticamente. Si alguno falla con un error de conexión, validar primero las credenciales del `.env`.

---

## Orden recomendado de ejecución

Los scripts están numerados según el orden recomendado. La razón del orden es que **cada uno informa al siguiente** — los volúmenes que descubre el `01` afectan cómo interpretar los tiempos del `04` y `05`.

| # | Script | Qué mide | Tiempo aprox. |
|---|---|---|---|
| 01 | `01_volumetria_fuentes.py` | Cantidad de filas y características por fuente | < 30s |
| 02 | `02_tiempo_conexiones.py` | Latencia de establecer cada conexión SQL/LDAP | < 10s |
| 03 | `03_tiempo_lectura_csv.py` | Velocidad de lectura de CSVs y Excel | < 60s |
| 04 | `04_ldap_unitario.py` | Costo real de UNA búsqueda LDAP aislada | < 5s |
| 05 | `05_ldap_batch.py` | **Comparativa clave**: conexión por iteración vs persistente | < 60s |
| 06 | `06_iterrows_vs_vectorizado.py` | Comparativa: iterrows anidado vs `.map()` | < 30s |
| 07 | `07_excel_vs_parquet.py` | Comparativa de velocidad de escritura | < 60s |
| 08 | `08_perfil_kactus.py` | % de identidades resolubles desde Kactus sin LDAP | < 10s |

**Tiempo total estimado de toda la batería: 4-5 minutos.**

---

## Ejecución

### Opción 1: correr uno por uno (recomendado para iteración)

```bash
python diagnostics/01_volumetria_fuentes.py
python diagnostics/02_tiempo_conexiones.py
# ... etc
```

### Opción 2: correr todos en secuencia

```bash
python diagnostics/run_all.py
```

Esto ejecuta los 8 scripts en orden y consolida los resultados en `diagnostics/resultados/diagnostico_empirico.md`.

---

## Interpretación de resultados

Cada script imprime al final una sección **`CONCLUSIÓN TENTATIVA`** con un veredicto preliminar. Estas conclusiones individuales se consolidan en el documento `docs/diagnostico_empirico.md` que cierra esta etapa y alimenta la Fase 2.

**Las decisiones de diseño que dependen de estos resultados son:**

- **¿Vale la pena el LDAP batch + persistente?** → lo decide `05_ldap_batch.py`.
- **¿Vale la pena migrar de Excel a Parquet para intermedios?** → lo decide `07_excel_vs_parquet.py`.
- **¿La carga incremental tiene impacto significativo?** → lo decide `01_volumetria_fuentes.py` + `02_tiempo_conexiones.py`.
- **¿Qué porcentaje de cédulas necesita realmente LDAP?** → lo decide `08_perfil_kactus.py`.

---

## Resultados

Los resultados de cada corrida quedan en `diagnostics/resultados/` como archivos markdown con timestamp. Esto permite versionar la evidencia y comparar mediciones a lo largo del tiempo.

---

*Una vez tomadas las decisiones de diseño, esta carpeta se mantiene en el repo como evidencia histórica pero no se modifica más. La Fase 2 producirá `docs/fase2_profiling.md` con el resumen ejecutivo de todo esto.*