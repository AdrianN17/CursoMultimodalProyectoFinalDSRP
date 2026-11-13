"""Checkpointer de LangGraph sobre Azure SQL / SQL Server (T-SQL + pyodbc).

Por qué existe: `langgraph-checkpoint-mssql` (comunitario) exige Python >= 3.12 y este proyecto usa 3.11.
Sigue el mismo diseño que InMemorySaver/PostgresSaver: el checkpoint se guarda SIN channel_values y cada
canal se guarda aparte versionado (checkpoint_blobs), más las escrituras pendientes (checkpoint_writes),
que son las que permiten reanudar un `interrupt()` (HITL) horas después.
"""
from __future__ import annotations

import functools
import json
import time
from collections.abc import Iterator, Sequence
from typing import Any

import pyodbc
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
    get_checkpoint_metadata,
    writes_sort_key,
)

from .. import db

DDL = [
    """IF OBJECT_ID('checkpoints') IS NULL CREATE TABLE checkpoints (
        thread_id VARCHAR(100) NOT NULL, checkpoint_ns VARCHAR(200) NOT NULL CONSTRAINT DF_ck_ns DEFAULT '',
        checkpoint_id VARCHAR(100) NOT NULL, parent_checkpoint_id VARCHAR(100) NULL, [type] VARCHAR(50) NULL,
        [checkpoint] VARBINARY(MAX) NOT NULL, [metadata] VARBINARY(MAX) NOT NULL,
        creado_en DATETIME2 NOT NULL CONSTRAINT DF_ck_creado DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_checkpoints PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id))""",
    """IF OBJECT_ID('checkpoint_blobs') IS NULL CREATE TABLE checkpoint_blobs (
        thread_id VARCHAR(100) NOT NULL, checkpoint_ns VARCHAR(200) NOT NULL CONSTRAINT DF_cb_ns DEFAULT '',
        channel VARCHAR(200) NOT NULL, [version] VARCHAR(100) NOT NULL, [type] VARCHAR(50) NOT NULL,
        [blob] VARBINARY(MAX) NULL,
        CONSTRAINT PK_checkpoint_blobs PRIMARY KEY (thread_id, checkpoint_ns, channel, [version]))""",
    """IF OBJECT_ID('checkpoint_writes') IS NULL CREATE TABLE checkpoint_writes (
        thread_id VARCHAR(100) NOT NULL, checkpoint_ns VARCHAR(200) NOT NULL CONSTRAINT DF_cw_ns DEFAULT '',
        checkpoint_id VARCHAR(100) NOT NULL, task_id VARCHAR(100) NOT NULL, idx INT NOT NULL,
        channel VARCHAR(200) NOT NULL, [type] VARCHAR(50) NULL, [blob] VARBINARY(MAX) NOT NULL,
        task_path VARCHAR(400) NOT NULL CONSTRAINT DF_cw_path DEFAULT '',
        CONSTRAINT PK_checkpoint_writes PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx))""",
]


def _reintentar_deadlock(fn):
    """Reintenta ante deadlock (1205): LangGraph escribe desde hilos concurrentes sobre el mismo thread."""
    @functools.wraps(fn)
    def envoltura(*a, **kw):
        for intento in range(5):
            try:
                return fn(*a, **kw)
            except pyodbc.Error as e:
                if "1205" not in str(e) or intento == 4:
                    raise
                time.sleep(0.05 * (intento + 1))
    return envoltura


def _insertar_ignorando_duplicado(cn: Any, sql: str, params: tuple) -> None:
    """INSERT que tolera la clave repetida (la primera escritura gana) sin bloqueos de rango: evita deadlocks."""
    try:
        cn.cursor().execute(sql, params)
    except pyodbc.IntegrityError:
        pass


class SqlServerSaver(BaseCheckpointSaver[str]):
    def __init__(self) -> None:
        super().__init__()

    def setup(self) -> None:
        with db.conexion(autocommit=True) as cn:
            for ddl in DDL:
                cn.cursor().execute(ddl)

    # ---- lectura ---------------------------------------------------------------------------
    def _cargar(self, cn: Any, fila: dict, thread_id: str, ns: str, config: RunnableConfig | None) -> CheckpointTuple:
        ck: Checkpoint = self.serde.loads_typed((fila["type"], bytes(fila["checkpoint"])))
        versiones = {k: str(v) for k, v in ck["channel_versions"].items()}
        valores: dict[str, Any] = {}
        for b in db.consultar("SELECT channel, [version], [type], [blob] FROM checkpoint_blobs "
                              "WHERE thread_id = ? AND checkpoint_ns = ?", (thread_id, ns), cn):
            if versiones.get(b["channel"]) == b["version"] and b["type"] != "empty" and b["blob"] is not None:
                valores[b["channel"]] = self.serde.loads_typed((b["type"], bytes(b["blob"])))
        escrituras = db.consultar(
            "SELECT task_id, idx, channel, [type], [blob], task_path FROM checkpoint_writes "
            "WHERE thread_id = ? AND checkpoint_ns = ? AND checkpoint_id = ?",
            (thread_id, ns, fila["checkpoint_id"]), cn)
        escrituras.sort(key=lambda w: writes_sort_key(w["task_path"], w["task_id"], w["idx"]))
        cfg = config if config and get_checkpoint_id(config) else {
            "configurable": {"thread_id": thread_id, "checkpoint_ns": ns, "checkpoint_id": fila["checkpoint_id"]}}
        padre = ({"configurable": {"thread_id": thread_id, "checkpoint_ns": ns,
                                   "checkpoint_id": fila["parent_checkpoint_id"]}}
                 if fila["parent_checkpoint_id"] else None)
        return CheckpointTuple(
            config=cfg,
            checkpoint={**ck, "channel_values": valores},
            metadata=json.loads(bytes(fila["metadata"]).decode("utf-8")),
            parent_config=padre,
            pending_writes=[(w["task_id"], w["channel"], self.serde.loads_typed((w["type"], bytes(w["blob"]))))
                            for w in escrituras],
        )

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        thread_id = config["configurable"]["thread_id"]
        ns = config["configurable"].get("checkpoint_ns", "")
        ck_id = get_checkpoint_id(config)
        with db.conexion() as cn:
            if ck_id:
                fila = db.uno("SELECT * FROM checkpoints WHERE thread_id = ? AND checkpoint_ns = ? "
                              "AND checkpoint_id = ?", (thread_id, ns, ck_id), cn)
            else:
                fila = db.uno("SELECT TOP 1 * FROM checkpoints WHERE thread_id = ? AND checkpoint_ns = ? "
                              "ORDER BY checkpoint_id DESC", (thread_id, ns), cn)
            return self._cargar(cn, fila, thread_id, ns, config) if fila else None

    def list(self, config: RunnableConfig | None, *, filter: dict[str, Any] | None = None,
             before: RunnableConfig | None = None, limit: int | None = None) -> Iterator[CheckpointTuple]:
        sql, params = "SELECT * FROM checkpoints WHERE 1 = 1", []
        if config:
            sql += " AND thread_id = ?"
            params.append(config["configurable"]["thread_id"])
            if "checkpoint_ns" in config["configurable"]:
                sql += " AND checkpoint_ns = ?"
                params.append(config["configurable"]["checkpoint_ns"])
            if cid := get_checkpoint_id(config):
                sql += " AND checkpoint_id = ?"
                params.append(cid)
        if before and (bid := get_checkpoint_id(before)):
            sql += " AND checkpoint_id < ?"
            params.append(bid)
        sql += " ORDER BY checkpoint_id DESC"
        with db.conexion() as cn:
            enviados = 0
            for fila in db.consultar(sql, params, cn):
                meta = json.loads(bytes(fila["metadata"]).decode("utf-8"))
                if filter and not all(meta.get(k) == v for k, v in filter.items()):
                    continue
                yield self._cargar(cn, fila, fila["thread_id"], fila["checkpoint_ns"], None)
                enviados += 1
                if limit is not None and enviados >= limit:
                    break

    # ---- escritura -------------------------------------------------------------------------
    @_reintentar_deadlock
    def put(self, config: RunnableConfig, checkpoint: Checkpoint, metadata: CheckpointMetadata,
            new_versions: ChannelVersions) -> RunnableConfig:
        thread_id = config["configurable"]["thread_id"]
        ns = config["configurable"].get("checkpoint_ns", "")
        ck = checkpoint.copy()
        valores: dict[str, Any] = ck.pop("channel_values")  # type: ignore[misc]
        with db.conexion() as cn:
            for canal, version in new_versions.items():
                tipo, blob = self.serde.dumps_typed(valores[canal]) if canal in valores else ("empty", b"")
                _insertar_ignorando_duplicado(
                    cn, "INSERT INTO checkpoint_blobs (thread_id, checkpoint_ns, channel, [version], [type], [blob]) "
                        "VALUES (?, ?, ?, ?, ?, ?)", (thread_id, ns, canal, str(version), tipo, blob))
            tipo_ck, blob_ck = self.serde.dumps_typed(ck)
            meta = json.dumps(get_checkpoint_metadata(config, metadata), ensure_ascii=False,
                              default=str).encode("utf-8")
            padre = config["configurable"].get("checkpoint_id")
            upd = ("UPDATE checkpoints SET parent_checkpoint_id = ?, [type] = ?, [checkpoint] = ?, [metadata] = ? "
                   "WHERE thread_id = ? AND checkpoint_ns = ? AND checkpoint_id = ?")
            p_upd = (padre, tipo_ck, blob_ck, meta, thread_id, ns, checkpoint["id"])
            if db.ejecutar(upd, p_upd, cn) == 0:
                try:
                    db.ejecutar(
                        "INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, "
                        "[type], [checkpoint], [metadata]) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (thread_id, ns, checkpoint["id"], padre, tipo_ck, blob_ck, meta), cn)
                except pyodbc.IntegrityError:
                    db.ejecutar(upd, p_upd, cn)
        return {"configurable": {"thread_id": thread_id, "checkpoint_ns": ns, "checkpoint_id": checkpoint["id"]}}

    @_reintentar_deadlock
    def put_writes(self, config: RunnableConfig, writes: Sequence[tuple[str, Any]], task_id: str,
                   task_path: str = "") -> None:
        thread_id = config["configurable"]["thread_id"]
        ns = config["configurable"].get("checkpoint_ns", "")
        ck_id = config["configurable"]["checkpoint_id"]
        ins = ("INSERT INTO checkpoint_writes (thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, "
               "[type], [blob], task_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)")
        with db.conexion() as cn:
            for idx, (canal, valor) in enumerate(writes):
                i = WRITES_IDX_MAP.get(canal, idx)
                tipo, blob = self.serde.dumps_typed(valor)
                clave = (thread_id, ns, ck_id, task_id, i)
                if i >= 0:  # escrituras normales: la primera gana, no se sobrescriben
                    _insertar_ignorando_duplicado(cn, ins, (*clave, canal, tipo, blob, task_path))
                else:  # escrituras especiales (interrupt, error...): reemplazan
                    db.ejecutar("DELETE FROM checkpoint_writes WHERE thread_id = ? AND checkpoint_ns = ? "
                                "AND checkpoint_id = ? AND task_id = ? AND idx = ?", clave, cn)
                    db.ejecutar(ins, (*clave, canal, tipo, blob, task_path), cn)

    def delete_thread(self, thread_id: str) -> None:
        with db.conexion() as cn:
            for t in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
                db.ejecutar(f"DELETE FROM {t} WHERE thread_id = ?", (thread_id,), cn)
