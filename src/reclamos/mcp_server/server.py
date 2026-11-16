"""Servidor MCP (stdio) que expone las tools de negocio sobre Azure SQL.

Ejecutar:  python -m reclamos.mcp_server.server
OJO: en stdio, stdout es el canal del protocolo; nada debe imprimirse allí (los logs van a stderr).
"""
from __future__ import annotations

import logging
import sys

from mcp.server.fastmcp import FastMCP

from ..observabilidad.otel import iniciar_registro
from . import tools

logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
iniciar_registro("mcp_server")  # hereda REGISTRO_ARCHIVO del proceso padre: mismo fichero en temporal/

mcp = FastMCP("reclamos-bancarios")

for _nombre, _fn in tools.REGISTRO.items():
    mcp.tool(name=_nombre, description=(_fn.__doc__ or _nombre).strip())(_fn)


if __name__ == "__main__":
    mcp.run(transport="stdio")
