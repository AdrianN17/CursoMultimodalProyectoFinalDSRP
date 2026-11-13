"""Aplica el esquema SQL del changelog de Liquibase SIN Liquibase (solo desarrollo local).

El camino oficial es Liquibase (docker compose run --rm liquibase). Este script existe para equipos
sin Java/Docker: lee el MISMO db.changelog-master.yaml y ejecuta los mismos .sql, registrando los
changeSets en la tabla __CAMBIOS_LOCALES. No mezclar con Liquibase sobre la misma base.

Uso:  python scripts/aplicar_esquema.py [--reset]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from reclamos import db  # noqa: E402

CHANGELOG = RAIZ / "db" / "changelog" / "db.changelog-master.yaml"


def _sentencias(sql: str) -> list[str]:
    sin_comentarios = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))
    return [s.strip() for s in re.split(r";\s*(?:\r?\n|$)", sin_comentarios) if s.strip()]


def resetear() -> None:
    with db.conexion(autocommit=True) as cn:
        cur = cn.cursor()
        for fila in cur.execute(
            "SELECT OBJECT_NAME(parent_object_id) AS t, name FROM sys.foreign_keys"
        ).fetchall():
            cn.cursor().execute(f"ALTER TABLE [{fila.t}] DROP CONSTRAINT [{fila.name}]")
        for fila in cn.cursor().execute("SELECT name FROM sys.tables").fetchall():
            cn.cursor().execute(f"DROP TABLE [{fila.name}]")
    print("Base reiniciada (todas las tablas eliminadas).")


def aplicar() -> None:
    master = yaml.safe_load(CHANGELOG.read_text(encoding="utf-8"))
    with db.conexion(autocommit=True) as cn:
        cn.cursor().execute(
            "IF OBJECT_ID('__CAMBIOS_LOCALES') IS NULL CREATE TABLE __CAMBIOS_LOCALES (id VARCHAR(100) PRIMARY KEY)"
        )
        hechos = {f.id for f in cn.cursor().execute("SELECT id FROM __CAMBIOS_LOCALES").fetchall()}
        for item in master["databaseChangeLog"]:
            cs = item["changeSet"]
            if cs["id"] in hechos:
                print(f"= {cs['id']} (ya aplicado)")
                continue
            for cambio in cs["changes"]:
                ruta = CHANGELOG.parent / cambio["sqlFile"]["path"]
                for s in _sentencias(ruta.read_text(encoding="utf-8")):
                    cn.cursor().execute(s)
            cn.cursor().execute("INSERT INTO __CAMBIOS_LOCALES (id) VALUES (?)", (cs["id"],))
            print(f"+ {cs['id']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reset", action="store_true", help="elimina TODAS las tablas antes de aplicar")
    args = ap.parse_args()
    if args.reset:
        resetear()
    aplicar()
