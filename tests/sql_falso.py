"""Sustituto de `pyodbc` para pytest: SQLite en un archivo temporal, sin red ni Azure SQL.

Se instala en `sys.modules["pyodbc"]` ANTES de importar `reclamos`, de modo que `db.py`, el checkpointer y las tools
usan este módulo sin cambios. El esquema se construye desde el MISMO changelog YAML (createTable, addColumn,
createIndex, insert); los CHECK y las FK no se emulan (se validan contra SQL Server real con `-m integracion`).

Traducciones T-SQL -> SQLite que cubre (solo lo que usa el código): SELECT TOP n, SYSUTCDATETIME(), DATEADD,
IF OBJECT_ID(...) IS NULL CREATE TABLE, CONSTRAINT <nombre> DEFAULT, (MAX).
"""
from __future__ import annotations

import re
import sqlite3
import sys
import tempfile
import types
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

_ARCHIVO = Path(tempfile.mkdtemp(prefix="reclamos_test_")) / "test.db"


class Error(Exception):
    pass


class IntegrityError(Error):
    pass


def _ahora() -> str:
    return datetime.utcnow().isoformat(sep=" ", timespec="microseconds")


def _dateadd(parte: str, n: int, valor: str | None) -> str | None:
    if valor is None:
        return None
    unidad = {"HOUR": "hours", "MINUTE": "minutes", "SECOND": "seconds", "DAY": "days"}[parte.upper()]
    base = datetime.fromisoformat(valor)
    return (base + timedelta(**{unidad: int(n)})).isoformat(sep=" ", timespec="microseconds")


sqlite3.register_adapter(datetime, lambda d: d.isoformat(sep=" ", timespec="microseconds"))
sqlite3.register_adapter(date, lambda d: d.isoformat())
sqlite3.register_adapter(Decimal, str)
sqlite3.register_converter("DATETIME2", lambda b: datetime.fromisoformat(b.decode()))
sqlite3.register_converter("DATE", lambda b: date.fromisoformat(b.decode()[:10]))
sqlite3.register_converter("DECIMAL", lambda b: Decimal(b.decode()))
sqlite3.register_converter("BIT", lambda b: bool(int(b)))


def _traducir(sql: str) -> str | None:
    """T-SQL -> SQLite. Devuelve None si la sentencia es un no-op en el sustituto."""
    s = sql.strip()
    if re.match(r"IF NOT EXISTS \(SELECT 1 FROM Servicio", s, re.I):
        return None  # el catálogo ya lo cargó el changeSet 007
    s = re.sub(r"IF OBJECT_ID\('\w+'\) IS NULL CREATE TABLE", "CREATE TABLE IF NOT EXISTS", s, flags=re.I)
    s = re.sub(r"CONSTRAINT \w+ DEFAULT", "DEFAULT", s)
    s = re.sub(r"DEFAULT SYSUTCDATETIME\(\)", "DEFAULT CURRENT_TIMESTAMP", s)
    s = re.sub(r"\(MAX\)", "", s, flags=re.I)
    s = re.sub(r"DATEADD\((\w+),", r"DATEADD('\1',", s, flags=re.I)
    m = re.match(r"(\s*SELECT\s+)TOP\s+(\d+)\s+(.*)$", s, re.I | re.S)
    if m:
        s = f"{m.group(1)}{m.group(3).rstrip().rstrip(';')} LIMIT {m.group(2)}"
    return s


class _Cursor:
    def __init__(self, cn: sqlite3.Connection):
        self._cur = cn.cursor()

    def execute(self, sql: str, params=()):
        traducida = _traducir(sql)
        if traducida is None:
            return self
        try:
            self._cur.execute(traducida, tuple(params))
        except sqlite3.IntegrityError as e:
            raise IntegrityError(str(e)) from e
        except sqlite3.Error as e:
            raise Error(f"{e} :: {traducida[:200]}") from e
        return self

    @property
    def description(self):
        return self._cur.description

    @property
    def rowcount(self):
        return self._cur.rowcount

    def fetchall(self):
        return self._cur.fetchall()

    def fetchone(self):
        return self._cur.fetchone()


class _Connection:
    timeout = 0

    def __init__(self, autocommit: bool):
        self._cn = sqlite3.connect(_ARCHIVO, timeout=30, detect_types=sqlite3.PARSE_DECLTYPES,
                                   isolation_level=None if autocommit else "")
        self._cn.create_function("SYSUTCDATETIME", 0, _ahora)
        self._cn.create_function("DATEADD", 3, _dateadd)

    def cursor(self):
        return _Cursor(self._cn)

    def commit(self):
        self._cn.commit()

    def rollback(self):
        self._cn.rollback()

    def close(self):
        self._cn.close()


def connect(_cadena: str = "", autocommit: bool = False, **_kw) -> _Connection:
    return _Connection(autocommit)


# ------------------------------------------------------------------ esquema desde el changelog YAML
def _tipo(c: dict) -> str:
    return re.sub(r"\(MAX\)", "", c["type"], flags=re.I)


def _default(c: dict) -> str:
    if "defaultValueComputed" in c:
        return " DEFAULT CURRENT_TIMESTAMP"
    if "defaultValueBoolean" in c:
        return f" DEFAULT {int(c['defaultValueBoolean'])}"
    if "defaultValueNumeric" in c:
        return f" DEFAULT {c['defaultValueNumeric']}"
    if "defaultValue" in c:
        return " DEFAULT '" + str(c["defaultValue"]).replace("'", "''") + "'"
    return ""


def _columna(c: dict) -> str:
    k = c.get("constraints", {})
    if c.get("autoIncrement"):
        return f"[{c['name']}] INTEGER PRIMARY KEY AUTOINCREMENT"
    nulo = " NOT NULL" if k.get("nullable") is False or k.get("primaryKey") else ""
    return f"[{c['name']}] {_tipo(c)}{nulo}{_default(c)}"


def construir_esquema(cargar_changelog) -> None:
    cn = sqlite3.connect(_ARCHIVO, detect_types=sqlite3.PARSE_DECLTYPES, isolation_level=None)
    for item in cargar_changelog():
        for cambio in item["changeSet"]["changes"]:
            (tipo, a), = cambio.items()
            if tipo == "createTable":
                cols = [x["column"] for x in a["columns"]]
                lineas = [_columna(c) for c in cols]
                pk = [c for c in cols if c.get("constraints", {}).get("primaryKey") and not c.get("autoIncrement")]
                if pk:
                    lineas.append(f"PRIMARY KEY ({', '.join(c['name'] for c in pk)})")
                lineas += [f"UNIQUE ([{c['name']}])" for c in cols if c.get("constraints", {}).get("unique")]
                cn.execute(f"CREATE TABLE [{a['tableName']}] ({', '.join(lineas)})")
            elif tipo == "addColumn":
                for x in a["columns"]:
                    cn.execute(f"ALTER TABLE [{a['tableName']}] ADD COLUMN {_columna(x['column'])}")
            elif tipo == "createIndex":
                cols = ", ".join(f"[{x['column']['name']}]" for x in a["columns"])
                unico = "UNIQUE " if a.get("unique") else ""
                cn.execute(f"CREATE {unico}INDEX {a['indexName']} ON [{a['tableName']}] ({cols})")
            elif tipo == "insert":
                cols = [x["column"] for x in a["columns"]]
                cn.execute(f"INSERT INTO [{a['tableName']}] ({', '.join(c['name'] for c in cols)}) "
                           f"VALUES ({', '.join('?' for _ in cols)})",
                           tuple(c["valueNumeric"] if "valueNumeric" in c else c["value"] for c in cols))
    cn.close()


def instalar(cargar_changelog) -> None:
    """Registra este módulo como `pyodbc` y crea el esquema en el archivo temporal."""
    mod = types.ModuleType("pyodbc")
    mod.connect, mod.Error, mod.IntegrityError = connect, Error, IntegrityError
    mod.Connection, mod.Cursor = _Connection, _Cursor
    sys.modules["pyodbc"] = mod
    construir_esquema(cargar_changelog)
