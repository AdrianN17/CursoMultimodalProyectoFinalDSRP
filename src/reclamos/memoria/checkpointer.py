"""Fábrica del checkpointer (memoria entre interacciones y reanudación del HITL) en Azure SQL."""
from __future__ import annotations

from .sqlserver_saver import SqlServerSaver


def crear_checkpointer() -> SqlServerSaver:
    saver = SqlServerSaver()
    saver.setup()  # crea checkpoints / checkpoint_blobs / checkpoint_writes si no existen
    return saver
