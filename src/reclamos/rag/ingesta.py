"""Ingesta e indexación del documento de políticas en Qdrant (un punto por política, con su ID estable)."""
from __future__ import annotations

import atexit
import re
from pathlib import Path
from threading import Lock

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from ..config import RAIZ, get_settings
from ..observabilidad.otel import trazar
from ..proveedores.interfaces import ProveedorIA

RUTA_POLITICAS = RAIZ / "rag" / "politicas_reclamacion.md"
_CLIENTES: dict[str, QdrantClient] = {}
_LOCK = Lock()


def cerrar_clientes() -> None:
    for c in _CLIENTES.values():
        try:
            c.close()
        except Exception:  # cierre en apagado: nada que recuperar
            pass
    _CLIENTES.clear()


atexit.register(cerrar_clientes)  # evita el ImportError de QdrantClient.__del__ durante el apagado del intérprete


def obtener_cliente() -> QdrantClient:
    s = get_settings()
    clave = s.qdrant_url or s.qdrant_path
    with _LOCK:
        if clave not in _CLIENTES:
            _CLIENTES[clave] = (QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key or None)
                                if s.qdrant_url else QdrantClient(path=s.qdrant_path))
        return _CLIENTES[clave]


def parsear_politicas(ruta: Path = RUTA_POLITICAS) -> tuple[str, list[dict]]:
    texto = ruta.read_text(encoding="utf-8")
    version = (re.search(r"version:\s*([\w.]+)", texto) or [None, "0"])[1]
    politicas = []
    for bloque in re.split(r"(?m)^## ", texto)[1:]:
        cabecera, _, cuerpo = bloque.partition("\n")
        m = re.match(r"(P-\d{2})\s*·\s*(.+)", cabecera.strip())
        if m:
            politicas.append({"policy_id": m.group(1), "titulo": m.group(2).strip(),
                              "texto": f"{m.group(1)} · {m.group(2).strip()}. {cuerpo.strip()}", "version": version})
    return version, politicas


def indexar(proveedor: ProveedorIA, forzar: bool = False) -> int:
    """Crea/actualiza la colección si falta o si cambió la versión del documento. Devuelve nº de políticas."""
    s = get_settings()
    cli = obtener_cliente()
    version, politicas = parsear_politicas()
    with trazar("rag.indexar", **{"rag.version": version, "rag.n_politicas": len(politicas)}) as sp:
        if not forzar and cli.collection_exists(s.qdrant_coleccion):
            puntos, _ = cli.scroll(s.qdrant_coleccion, limit=1, with_payload=True)
            if puntos and puntos[0].payload.get("version") == version:
                sp.set_attribute("rag.reindexado", False)
                return len(politicas)
        vectores = proveedor.embeber([p["texto"] for p in politicas])
        if cli.collection_exists(s.qdrant_coleccion):
            cli.delete_collection(s.qdrant_coleccion)
        cli.create_collection(s.qdrant_coleccion,
                              vectors_config=VectorParams(size=len(vectores[0]), distance=Distance.COSINE))
        cli.upsert(s.qdrant_coleccion, points=[
            PointStruct(id=i, vector=v, payload=p) for i, (p, v) in enumerate(zip(politicas, vectores))])
        sp.set_attribute("rag.reindexado", True)
        return len(politicas)
