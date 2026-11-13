# Falla 1 — Deadlock del checkpointer en Azure SQL

**Archivos relacionados:** `src/reclamos/memoria/sqlserver_saver.py` (`put`, `put_writes`), `tests/test_persistencia_herramientas.py`.

## Síntoma
Primera ejecución completa del grafo (`main.py --caso-id C-07 --semilla 4213 --aprobar APROBADA`) terminó con:

```
File ".../memoria/sqlserver_saver.py", line 168, in put_writes
pyodbc.Error: ('40001', '[40001] [Microsoft][ODBC Driver 18 for SQL Server][SQL Server]Transaction (Process ID 53)
was deadlocked on lock resources with another process and has been chosen as the deadlock victim. (1205)')
```

## Hipótesis inicial
Dos hilos de LangGraph (`put_writes` se ejecuta desde un pool de hilos) escriben a la vez en `checkpoint_writes` y el patrón
`IF NOT EXISTS … INSERT` no es atómico → condición de carrera por claves duplicadas.

## Diagnóstico
1. Primera corrección: `IF NOT EXISTS (SELECT … WITH (UPDLOCK, HOLDLOCK))` más un decorador `_reintentar_deadlock` ante el error 1205.
   El error inmediato desapareció, pero el rendimiento empeoró:
   - Suite completa: **678.85 s** y un fallo `pyodbc.OperationalError HYT00` (timeout de consulta) en `put_writes`.
   - Otra ejecución de la suite: 37.9 s, con flujos individuales de 7–9 s (`--durations`).
2. `HOLDLOCK` equivale a `SERIALIZABLE`: toma **bloqueos de rango de clave**. Dos hilos que insertan claves *distintas* dentro del mismo rango de la PK
   se bloquean entre sí y el motor tarda en elegir una víctima.

## Causa raíz (distinta de la hipótesis)
No era una carrera por duplicados: las claves nunca colisionaban. El problema eran los **bloqueos de rango** que generaba el propio patrón *check-then-insert*
(agravado por `HOLDLOCK`).

## Solución
Insertar directamente y tratar la violación de PK como "ya existe" (`_insertar_ignorando_duplicado`); para el checkpoint, `UPDATE` y, si no afecta filas,
`INSERT` con reintento a `UPDATE`. Se mantiene `_reintentar_deadlock` como red de seguridad.
Resultado: suite completa en **9.71 s** (59 pruebas en ese momento).

## Aprendizaje
En SQL Server evite *check-then-insert* con hints de aislamiento alto; deje que la PK sea el árbitro. Mida con `--durations`: un error "resuelto" puede dejar una regresión de latencia.
