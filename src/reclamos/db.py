"""Acceso a Azure SQL / SQL Server mediante pyodbc. Siempre consultas parametrizadas."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

import pyodbc

from .config import get_settings


@contextmanager
def conexion(autocommit: bool = False) -> Iterator[pyodbc.Connection]:
    cn = pyodbc.connect(get_settings().sql_conn_str(), autocommit=autocommit)
    cn.timeout = 20
    try:
        yield cn
        if not autocommit:
            cn.commit()
    except Exception:
        if not autocommit:
            cn.rollback()
        raise
    finally:
        cn.close()


def _filas(cur: pyodbc.Cursor) -> list[dict[str, Any]]:
    if cur.description is None:
        return []
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, fila)) for fila in cur.fetchall()]


def consultar(sql: str, params: tuple | list = (), cn: pyodbc.Connection | None = None) -> list[dict[str, Any]]:
    if cn is not None:
        return _filas(cn.cursor().execute(sql, params))
    with conexion() as c:
        return _filas(c.cursor().execute(sql, params))


def uno(sql: str, params: tuple | list = (), cn: pyodbc.Connection | None = None) -> dict[str, Any] | None:
    filas = consultar(sql, params, cn)
    return filas[0] if filas else None


def ejecutar(sql: str, params: tuple | list = (), cn: pyodbc.Connection | None = None) -> int:
    if cn is not None:
        return cn.cursor().execute(sql, params).rowcount
    with conexion() as c:
        return c.cursor().execute(sql, params).rowcount
