"""Cliente de tools: MCP por stdio (producción/demo) o in-process (pruebas rápidas). Instrumenta cada llamada."""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import sys
import threading
import time
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from ..config import get_settings
from ..observabilidad.otel import poner_atributo, trace_id_actual, trazar
from . import tools

ERRORES_TECNICOS = {"DB_ERROR", "ERROR_INTERNO", "MCP_TIMEOUT", "MCP_ERROR"}
SRC = Path(__file__).resolve().parents[2]


class _PuenteStdio:
    """Sesión MCP persistente sobre un hilo con su propio event loop (el grafo es síncrono)."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True, name="mcp-loop").start()
        self._pila: AsyncExitStack | None = None
        self._sesion: Any = None
        asyncio.run_coroutine_threadsafe(self._abrir(), self.loop).result(timeout=45)

    async def _abrir(self) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        entorno = {**os.environ, "PYTHONPATH": str(SRC) + os.pathsep + os.environ.get("PYTHONPATH", "")}
        params = StdioServerParameters(command=sys.executable, args=["-m", "reclamos.mcp_server.server"],
                                       env=entorno)
        self._pila = AsyncExitStack()
        leer, escribir = await self._pila.enter_async_context(stdio_client(params))
        self._sesion = await self._pila.enter_async_context(ClientSession(leer, escribir))
        await self._sesion.initialize()

    async def _llamar(self, nombre: str, args: dict) -> dict:
        r = await asyncio.wait_for(self._sesion.call_tool(nombre, args), timeout=30)
        if r.isError:
            texto = r.content[0].text if r.content else "error MCP"
            return {"ok": False, "error": {"codigo": "MCP_ERROR", "mensaje": texto[:200]}}
        sc = r.structuredContent
        if isinstance(sc, dict):
            return sc["result"] if set(sc) == {"result"} else sc
        return json.loads(r.content[0].text)

    def llamar(self, nombre: str, args: dict) -> dict:
        try:
            return asyncio.run_coroutine_threadsafe(self._llamar(nombre, args), self.loop).result(timeout=40)
        except (asyncio.TimeoutError, TimeoutError):
            return {"ok": False, "error": {"codigo": "MCP_TIMEOUT", "mensaje": "La tool no respondió a tiempo",
                                           "reintentable": True}}

    def cerrar(self) -> None:
        if self._pila is not None:
            try:
                asyncio.run_coroutine_threadsafe(self._pila.aclose(), self.loop).result(timeout=10)
            except Exception:
                pass
        self.loop.call_soon_threadsafe(self.loop.stop)


class ClienteHerramientas:
    def __init__(self, transporte: str | None = None) -> None:
        self.transporte = (transporte or get_settings().mcp_transport).lower()
        self._puente: _PuenteStdio | None = None
        self._lock = threading.Lock()

    def _ejecutar(self, nombre: str, args: dict) -> dict:
        if self.transporte == "inproc":
            return tools.REGISTRO[nombre](**args)
        with self._lock:
            if self._puente is None:
                self._puente = _PuenteStdio()
        return self._puente.llamar(nombre, args)

    def llamar(self, nombre: str, **args: Any) -> dict:
        """Siempre devuelve el sobre {"ok", "data"|"error"}; reintenta 1 vez los errores reintentables."""
        if nombre not in tools.REGISTRO:
            return {"ok": False, "error": {"codigo": "TOOL_DESCONOCIDA", "mensaje": nombre}}
        if "trace_id" in inspect.signature(tools.REGISTRO[nombre]).parameters:
            args.setdefault("trace_id", trace_id_actual() or "")
        with trazar(f"tool.{nombre}", **{"tool.name": nombre, "tool.transporte": self.transporte,
                                         "tool.args": {k: v for k, v in args.items() if k != "trace_id"}}) as sp:
            t0 = time.perf_counter()
            res = self._ejecutar(nombre, args)
            if not res.get("ok") and res.get("error", {}).get("reintentable"):
                sp.add_event("reintento", {"motivo": res["error"]["codigo"]})
                time.sleep(0.3)
                res = self._ejecutar(nombre, args)
            sp.set_attribute("tool.ok", bool(res.get("ok")))
            sp.set_attribute("tool.latencia_ms", round((time.perf_counter() - t0) * 1000, 2))
            if res.get("ok"):
                poner_atributo(sp, "tool.resultado", res["data"])
            else:
                err = res.get("error", {})
                sp.set_attribute("tool.error.codigo", err.get("codigo", "?"))
                poner_atributo(sp, "tool.error.mensaje", err.get("mensaje"))
                if err.get("codigo") in ERRORES_TECNICOS:
                    from opentelemetry.trace import Status, StatusCode
                    sp.set_status(Status(StatusCode.ERROR, err.get("codigo")))
            return res

    def cerrar(self) -> None:
        if self._puente is not None:
            self._puente.cerrar()
            self._puente = None
