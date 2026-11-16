"""Recuperación de políticas (RAG). El RAG JUSTIFICA y cita; el motor de reglas DECIDE."""
from __future__ import annotations

import logging

from ..config import get_settings
from ..observabilidad.otel import trazar
from ..proveedores.interfaces import ProveedorIA
from .ingesta import indexar, obtener_cliente

log = logging.getLogger("reclamos.rag")


class RetrieverPoliticas:
    def __init__(self, proveedor: ProveedorIA):
        self.prov = proveedor
        indexar(proveedor)  # asegura el índice (idempotente por versión)

    def buscar(self, consulta: str, k: int = 3, obligatorias: list[str] | None = None) -> list[dict]:
        """Top-k semántico + políticas que el motor ya sabe aplicables (se garantiza su cita)."""
        s = get_settings()
        with trazar("rag.recuperar", **{"rag.k": k, "rag.consulta": consulta[:200]}) as sp:
            vector = self.prov.embeber([consulta])[0]
            puntos = obtener_cliente().query_points(s.qdrant_coleccion, query=vector, limit=k,
                                                    with_payload=True).points
            res = {p.payload["policy_id"]: {**p.payload, "score": round(float(p.score), 4)} for p in puntos}
            for pid in obligatorias or []:
                if pid not in res:
                    r = obtener_cliente().scroll(s.qdrant_coleccion, limit=50, with_payload=True)[0]
                    for p in r:
                        if p.payload["policy_id"] == pid:
                            res[pid] = {**p.payload, "score": None}
            out = list(res.values())
            log.info("RAG: consulta de %d caracteres -> %s", len(consulta),
                     ", ".join(f"{x['policy_id']}({x['score']})" for x in out))
            log.debug("RAG consulta: %s | obligatorias=%s", consulta[:200], obligatorias or [])
            sp.set_attribute("rag.policy_ids", ",".join(x["policy_id"] for x in out))
            sp.set_attribute("rag.scores", ",".join(str(x["score"]) for x in out))
            return out
