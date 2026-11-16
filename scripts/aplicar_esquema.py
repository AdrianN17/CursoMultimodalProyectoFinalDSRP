"""Aplica el esquema SQL del changelog de Liquibase SIN Liquibase (solo desarrollo local).

El camino oficial es Liquibase (docker compose run --rm liquibase). Este script existe para equipos
sin Java/Docker: lee el MISMO db.changelog-master.yaml (cambios YAML nativos: createTable, addColumn,
addForeignKeyConstraint, createIndex, insert, sql), los traduce a T-SQL y registra los
changeSets en la tabla __CAMBIOS_LOCALES. Todo se crea en el esquema AZURE_SQL_SCHEMA (por defecto `multimodal`),
que el script crea si no existe. No mezclar con Liquibase sobre la misma base.

Uso:  python scripts/aplicar_esquema.py [--reset] [--sql]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from reclamos import db  # noqa: E402
from reclamos.config import get_settings  # noqa: E402

CHANGELOG = RAIZ / "db" / "changelog" / "db.changelog-master.yaml"


def _cargar(ruta: Path) -> list[dict]:
    """Aplana el changelog resolviendo los `include` (misma semántica que Liquibase, en orden)."""
    items: list[dict] = []
    for item in yaml.safe_load(ruta.read_text(encoding="utf-8"))["databaseChangeLog"]:
        if "include" in item:
            inc = item["include"]
            base = ruta.parent if inc.get("relativeToChangelogFile") else CHANGELOG.parent
            items += _cargar(base / inc["file"])
        else:
            items.append(item)
    return items


def _literal(v) -> str:
    return "'" + str(v).replace("'", "''") + "'"


def _esquema() -> str:
    return get_settings().sql_schema or "dbo"


def _t(tabla: str) -> str:
    """Nombre de tabla calificado con el esquema del proyecto."""
    return f"[{_esquema()}].[{tabla}]"


def _definicion_columna(c: dict) -> str:
    """Traduce una <column> de Liquibase a su definición T-SQL (tipo, IDENTITY, NULL, DEFAULT con nombre)."""
    k = c.get("constraints", {})
    partes = [f"[{c['name']}]", c["type"]]
    if c.get("autoIncrement"):
        partes.append("IDENTITY(1,1)")
    if k.get("nullable") is False or k.get("primaryKey"):
        partes.append("NOT NULL")
    default = None
    if "defaultValueComputed" in c:
        default = str(c["defaultValueComputed"])
    elif "defaultValueBoolean" in c:
        default = "1" if c["defaultValueBoolean"] else "0"
    elif "defaultValueNumeric" in c:
        default = str(c["defaultValueNumeric"])
    elif "defaultValue" in c:
        default = _literal(c["defaultValue"])
    if default is not None:
        nombre = c.get("defaultValueConstraintName")
        partes.append((f"CONSTRAINT {nombre} " if nombre else "") + f"DEFAULT {default}")
    return " ".join(partes)


def _sql_create_table(a: dict) -> str:
    cols = [x["column"] for x in a["columns"]]
    lineas = [_definicion_columna(c) for c in cols]
    pk = [c for c in cols if c.get("constraints", {}).get("primaryKey")]
    if pk:
        nombre = pk[0]["constraints"].get("primaryKeyName") or f"PK_{a['tableName']}"
        lineas.append(f"CONSTRAINT {nombre} PRIMARY KEY ({', '.join(c['name'] for c in pk)})")
    for c in cols:
        k = c.get("constraints", {})
        if k.get("unique"):
            lineas.append(f"CONSTRAINT {k.get('uniqueConstraintName') or 'UQ_' + a['tableName'] + '_' + c['name']} "
                          f"UNIQUE ([{c['name']}])")
    return f"CREATE TABLE {_t(a['tableName'])} (\n    " + ",\n    ".join(lineas) + "\n)"


def _sentencias_cambio(tipo: str, a: dict) -> list[tuple[str, tuple]]:
    """Convierte un cambio YAML de Liquibase en una o más sentencias T-SQL (con parámetros si los hay)."""
    if tipo == "createTable":
        return [(_sql_create_table(a), ())]
    if tipo == "addColumn":
        return [(f"ALTER TABLE {_t(a['tableName'])} ADD {_definicion_columna(x['column'])}", ()) for x in a["columns"]]
    if tipo == "addForeignKeyConstraint":
        return [(f"ALTER TABLE {_t(a['baseTableName'])} ADD CONSTRAINT {a['constraintName']} FOREIGN KEY "
                 f"({a['baseColumnNames']}) REFERENCES {_t(a['referencedTableName'])} "
                 f"({a['referencedColumnNames']})", ())]
    if tipo == "createIndex":
        cols = ", ".join(f"[{x['column']['name']}]" for x in a["columns"])
        unico = "UNIQUE " if a.get("unique") else ""
        return [(f"CREATE {unico}INDEX {a['indexName']} ON {_t(a['tableName'])} ({cols})", ())]
    if tipo == "insert":
        cols = [x["column"] for x in a["columns"]]
        valores = tuple(c["valueNumeric"] if "valueNumeric" in c else c["value"] for c in cols)
        return [(f"INSERT INTO {_t(a['tableName'])} ({', '.join(c['name'] for c in cols)}) "
                 f"VALUES ({', '.join('?' for _ in cols)})", valores)]
    if tipo == "sql":
        # Misma propiedad integrada que usa Liquibase en los `sql` crudos del changelog.
        texto = a["sql"].replace("${database.defaultSchemaName}", f"[{_esquema()}]")
        return [(s.strip(), ()) for s in texto.split(";") if s.strip()]
    raise NotImplementedError(f"Cambio de Liquibase no soportado por el runner local: {tipo}")


def resetear() -> None:
    """Elimina SOLO las tablas del esquema del proyecto (la base puede compartirse con otros proyectos)."""
    esquema = _esquema()
    if esquema.lower() == "dbo":
        sys.exit("--reset se niega a limpiar 'dbo': defina AZURE_SQL_SCHEMA (p. ej. multimodal).")
    with db.conexion(autocommit=True) as cn:
        fks = cn.cursor().execute(
            "SELECT OBJECT_NAME(f.parent_object_id) AS t, f.name FROM sys.foreign_keys f "
            "JOIN sys.tables t ON t.object_id = f.parent_object_id JOIN sys.schemas s ON s.schema_id = t.schema_id "
            "WHERE s.name = ?", (esquema,)).fetchall()
        for fila in fks:
            cn.cursor().execute(f"ALTER TABLE {_t(fila.t)} DROP CONSTRAINT [{fila.name}]")
        tablas = cn.cursor().execute(
            "SELECT t.name FROM sys.tables t JOIN sys.schemas s ON s.schema_id = t.schema_id WHERE s.name = ?",
            (esquema,)).fetchall()
        for fila in tablas:
            cn.cursor().execute(f"DROP TABLE {_t(fila.name)}")
    print(f"Esquema '{esquema}' reiniciado (solo sus tablas).")


def aplicar(solo_imprimir: bool = False) -> None:
    if solo_imprimir:
        print(f"-- esquema: {_esquema()}")
        for item in _cargar(CHANGELOG):
            cs = item["changeSet"]
            print(f"-- changeSet {cs['id']}")
            for cambio in cs["changes"]:
                (tipo, args), = cambio.items()
                for sentencia, params in _sentencias_cambio(tipo, args):
                    print(sentencia + (f"  -- params={params}" if params else "") + ";")
        return
    esquema, control = _esquema(), f"[{_esquema()}].[__CAMBIOS_LOCALES]"
    with db.conexion(autocommit=True) as cn:
        cn.cursor().execute(f"IF SCHEMA_ID('{esquema}') IS NULL EXEC('CREATE SCHEMA [{esquema}]')")
        cn.cursor().execute(
            f"IF OBJECT_ID('{esquema}.__CAMBIOS_LOCALES') IS NULL CREATE TABLE {control} (id VARCHAR(100) PRIMARY KEY)"
        )
        hechos = {f.id for f in cn.cursor().execute(f"SELECT id FROM {control}").fetchall()}
        for item in _cargar(CHANGELOG):
            cs = item["changeSet"]
            if cs["id"] in hechos:
                print(f"= {cs['id']} (ya aplicado)")
                continue
            for cambio in cs["changes"]:
                (tipo, args), = cambio.items()
                for sentencia, params in _sentencias_cambio(tipo, args):
                    cn.cursor().execute(sentencia, params)
            cn.cursor().execute(f"INSERT INTO {control} (id) VALUES (?)", (cs["id"],))
            print(f"+ {cs['id']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reset", action="store_true", help="elimina las tablas del esquema del proyecto antes de aplicar")
    ap.add_argument("--sql", action="store_true", help="solo imprime el T-SQL equivalente (no toca la BD)")
    args = ap.parse_args()
    if args.sql:
        aplicar(solo_imprimir=True)
        sys.exit(0)
    if args.reset:
        resetear()
    aplicar()
