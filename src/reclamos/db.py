"""Acceso a Azure SQL / SQL Server mediante pyodbc. Siempre consultas parametrizadas.

Todas las tablas del proyecto viven en un esquema propio (`AZURE_SQL_SCHEMA`, por defecto `multimodal`) para no
mezclarse con otros proyectos de la misma base. El código escribe SQL sin esquema y `calificar` lo antepone a las
tablas conocidas, de modo que ninguna consulta depende del esquema por defecto del usuario de la BD.
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Any, Iterator

import pyodbc

from .config import get_settings

TABLAS = (
    "Cliente", "Cuenta", "Balance", "Tarjeta", "Servicio", "Transaccion", "Ticket", "IdempotencyKey",
    "TicketEvento", "Evidencia", "Discrepancia", "AprobacionHitl", "Reembolso", "OtpChallenge", "LoginTrack",
    "EmailOutbox", "ParametroEscenario", "checkpoints", "checkpoint_blobs", "checkpoint_writes", "__CAMBIOS_LOCALES",
)
_NOMBRES = "|".join(sorted(TABLAS, key=len, reverse=True))
# Solo se califica el nombre de tabla conocido que sigue a FROM/JOIN/INTO/UPDATE/TABLE. No analiza literales:
# el código del proyecto no escribe esas combinaciones dentro de cadenas.
_RE_TABLA = re.compile(rf"(?i)\b(FROM|JOIN|INTO|UPDATE|TABLE)(\s+)(\[?)({_NOMBRES})(\]?)(?![\w.])")
_RE_OBJECT_ID = re.compile(rf"(?i)OBJECT_ID\('({_NOMBRES})'\)")


def calificar(sql: str, esquema: str) -> str:
    """Antepone `esquema.` a las tablas del proyecto. Con esquema vacío devuelve el SQL intacto."""
    if not esquema:
        return sql
    sql = _RE_TABLA.sub(lambda m: f"{m.group(1)}{m.group(2)}[{esquema}].[{m.group(4)}]", sql)
    return _RE_OBJECT_ID.sub(lambda m: f"OBJECT_ID('{esquema}.{m.group(1)}')", sql)


class _Cursor:
    def __init__(self, cur: Any, esquema: str):
        self._cur, self._esquema = cur, esquema

    def execute(self, sql: str, *params: Any) -> "_Cursor":
        self._cur.execute(calificar(sql, self._esquema), *params)
        return self

    def __getattr__(self, nombre: str) -> Any:
        return getattr(self._cur, nombre)


class _Conexion:
    """Envoltorio de la conexión: cada cursor califica las tablas con el esquema del proyecto."""

    def __init__(self, cn: Any, esquema: str):
        self._cn, self._esquema = cn, esquema

    def cursor(self) -> _Cursor:
        return _Cursor(self._cn.cursor(), self._esquema)

    def __getattr__(self, nombre: str) -> Any:
        return getattr(self._cn, nombre)


@contextmanager
def conexion(autocommit: bool = False) -> Iterator[_Conexion]:
    s = get_settings()
    cn = pyodbc.connect(s.sql_conn_str(), autocommit=autocommit)
    cn.timeout = 20
    try:
        yield _Conexion(cn, s.sql_schema)
        if not autocommit:
            cn.commit()
    except Exception:
        if not autocommit:
            cn.rollback()
        raise
    finally:
        cn.close()


def _filas(cur: Any) -> list[dict[str, Any]]:
    if cur.description is None:
        return []
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, fila)) for fila in cur.fetchall()]


def consultar(sql: str, params: tuple | list = (), cn: Any | None = None) -> list[dict[str, Any]]:
    if cn is not None:
        return _filas(cn.cursor().execute(sql, params))
    with conexion() as c:
        return _filas(c.cursor().execute(sql, params))


def uno(sql: str, params: tuple | list = (), cn: Any | None = None) -> dict[str, Any] | None:
    filas = consultar(sql, params, cn)
    return filas[0] if filas else None


def ejecutar(sql: str, params: tuple | list = (), cn: Any | None = None) -> int:
    if cn is not None:
        return cn.cursor().execute(sql, params).rowcount
    with conexion() as c:
        return c.cursor().execute(sql, params).rowcount
