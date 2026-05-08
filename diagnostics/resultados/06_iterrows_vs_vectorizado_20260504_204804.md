# Diagnóstico 06 — iterrows vs vectorizado

## Configuración

- N: 5,000, M: 1,000

## Tiempos

| Estrategia | Tiempo |
|---|---|
| A — iterrows() anidado | 50.65 s |
| B — .map() con dict | 6.9 ms |
| C — pd.merge | 5.0 ms |

**Speedup A→B:** 7351.7x
**Speedup A→C:** 10073.2x
