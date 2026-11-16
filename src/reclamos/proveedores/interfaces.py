"""Contrato de proveedores de IA (reemplazables). Los métodos públicos agregan span OTel + tokens/costo."""
from __future__ import annotations

import abc
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..observabilidad.otel import poner_atributo, registrar_uso_llm, trazar
from ..seguridad.sanitizar_pii import sanitizar

log = logging.getLogger("reclamos.ia")


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
        log.debug("LLM %s: solicitud al modelo '%s' (%s)", tarea, modelo, self.nombre)
        t0 = time.perf_counter()
        with trazar("llm.chat", **{"llm.tarea": tarea, "llm.rol_modelo": modelo, "llm.proveedor": self.nombre}) as sp:
            salida, uso, nombre_modelo = self._chat_json(tarea, system, payload_seguro, modelo)
            registrar_uso_llm(sp, nombre_modelo, uso.tokens_in, uso.tokens_out)
            poner_atributo(sp, "llm.salida", salida)
            log.info("LLM %s [%s]: %d tokens de entrada, %d de salida, %.1f s", tarea, nombre_modelo,
                     uso.tokens_in, uso.tokens_out, time.perf_counter() - t0)
            log.debug("LLM %s salida: %s", tarea, str(salida)[:600])
            return salida

    def transcribir(self, ruta: Path) -> str:
        log.debug("STT: transcribiendo %s (%d bytes)", ruta.name, ruta.stat().st_size)
        t0 = time.perf_counter()
        with trazar("stt.transcribir", **{"archivo": ruta.name, "llm.proveedor": self.nombre}) as sp:
            texto = self._transcribir(ruta)
            sp.set_attribute("stt.caracteres", len(texto))
            log.info("STT: %s -> %d caracteres en %.1f s", ruta.name, len(texto), time.perf_counter() - t0)
            log.debug("STT texto: %s", texto[:300])
            return texto

    def extraer_constancia(self, ruta: Path) -> dict[str, Any]:
        log.debug("Visión: leyendo la constancia %s (%d bytes)", ruta.name, ruta.stat().st_size)
        t0 = time.perf_counter()
        with trazar("vision.extraer_constancia", **{"archivo": ruta.name, "llm.proveedor": self.nombre}) as sp:
            datos, uso, modelo = self._extraer_constancia(ruta)
            registrar_uso_llm(sp, modelo, uso.tokens_in, uso.tokens_out)
            poner_atributo(sp, "vision.salida", datos)
            log.info("Visión [%s]: %s -> es_constancia=%s confianza=%s, %d tokens de entrada, %d de salida, %.1f s",
                     modelo, ruta.name, datos.get("es_constancia_pago"), datos.get("confianza"), uso.tokens_in,
                     uso.tokens_out, time.perf_counter() - t0)
            log.debug("Visión campos: %s", str(sanitizar(datos))[:600])
            return datos

    def sintetizar(self, texto: str, destino_sin_ext: Path) -> Path:
        t0 = time.perf_counter()
        with trazar("tts.sintetizar", **{"tts.caracteres": len(texto), "llm.proveedor": self.nombre}) as sp:
            ruta = self._sintetizar(texto, destino_sin_ext.with_suffix(self.extension_audio))
            sp.set_attribute("tts.bytes", ruta.stat().st_size)
            log.info("TTS: %d caracteres -> %s (%d bytes) en %.1f s", len(texto), ruta.name, ruta.stat().st_size,
                     time.perf_counter() - t0)
            return ruta

    def embeber(self, textos: list[str]) -> list[list[float]]:
        with trazar("rag.embed", **{"rag.n_textos": len(textos), "llm.proveedor": self.nombre}):
            vectores = self._embeber(textos)
            log.debug("Embeddings: %d textos -> vectores de %d dimensiones", len(textos),
                      len(vectores[0]) if vectores else 0)
            return vectores

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
