"""Contrato de proveedores de IA (reemplazables). Los métodos públicos agregan span OTel + tokens/costo."""
from __future__ import annotations

import abc
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..observabilidad.otel import poner_atributo, registrar_uso_llm, trazar
from ..seguridad.sanitizar_pii import sanitizar


@dataclass
class Uso:
    tokens_in: int = 0
    tokens_out: int = 0


class ProveedorIA(abc.ABC):
    nombre = "abstracto"
    extension_audio = ".mp3"

    # ---- API pública instrumentada ----------------------------------------------------------
    def chat_json(self, tarea: str, system: str, payload: dict[str, Any], modelo: str = "chat") -> dict[str, Any]:
        """`modelo`: 'router' (barato, clasificación) o 'chat' (razonamiento). El payload se sanitiza antes."""
        payload_seguro = sanitizar(payload)
        with trazar("llm.chat", **{"llm.tarea": tarea, "llm.rol_modelo": modelo, "llm.proveedor": self.nombre}) as sp:
            salida, uso, nombre_modelo = self._chat_json(tarea, system, payload_seguro, modelo)
            registrar_uso_llm(sp, nombre_modelo, uso.tokens_in, uso.tokens_out)
            poner_atributo(sp, "llm.salida", salida)
            return salida

    def transcribir(self, ruta: Path) -> str:
        with trazar("stt.transcribir", **{"archivo": ruta.name, "llm.proveedor": self.nombre}) as sp:
            texto = self._transcribir(ruta)
            sp.set_attribute("stt.caracteres", len(texto))
            return texto

    def extraer_constancia(self, ruta: Path) -> dict[str, Any]:
        with trazar("vision.extraer_constancia", **{"archivo": ruta.name, "llm.proveedor": self.nombre}) as sp:
            datos, uso, modelo = self._extraer_constancia(ruta)
            registrar_uso_llm(sp, modelo, uso.tokens_in, uso.tokens_out)
            poner_atributo(sp, "vision.salida", datos)
            return datos

    def sintetizar(self, texto: str, destino_sin_ext: Path) -> Path:
        with trazar("tts.sintetizar", **{"tts.caracteres": len(texto), "llm.proveedor": self.nombre}) as sp:
            ruta = self._sintetizar(texto, destino_sin_ext.with_suffix(self.extension_audio))
            sp.set_attribute("tts.bytes", ruta.stat().st_size)
            return ruta

    def embeber(self, textos: list[str]) -> list[list[float]]:
        with trazar("rag.embed", **{"rag.n_textos": len(textos), "llm.proveedor": self.nombre}):
            return self._embeber(textos)

    # ---- implementaciones ------------------------------------------------------------------
    @abc.abstractmethod
    def _chat_json(self, tarea: str, system: str, payload: dict, modelo: str) -> tuple[dict, Uso, str]: ...

    @abc.abstractmethod
    def _transcribir(self, ruta: Path) -> str: ...

    @abc.abstractmethod
    def _extraer_constancia(self, ruta: Path) -> tuple[dict, Uso, str]: ...

    @abc.abstractmethod
    def _sintetizar(self, texto: str, destino: Path) -> Path: ...

    @abc.abstractmethod
    def _embeber(self, textos: list[str]) -> list[list[float]]: ...


def obtener_proveedor() -> ProveedorIA:
    from ..config import get_settings

    s = get_settings()
    if s.proveedor == "mock":
        from .mock import ProveedorMock
        return ProveedorMock()
    if s.proveedor == "azure":
        from .azure_openai import ProveedorAzure
        return ProveedorAzure(s)
    raise ValueError(f"PROVEEDOR_IA desconocido: {s.proveedor} (use 'azure' o 'mock')")
