"""Proveedor Azure (Foundry): chat+visión y router con Azure OpenAI, embeddings, STT (MAI-Transcribe) y TTS (MAI-Voice)."""
from __future__ import annotations

import base64
import json
import logging
import mimetypes
import time
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

import httpx
from openai import AzureOpenAI

from ..agente.instrucciones import cargar_prompt
from ..config import Settings
from .interfaces import ProveedorIA, Uso

log = logging.getLogger("reclamos.ia.azure")


class ProveedorAzure(ProveedorIA):
    nombre = "azure"
    extension_audio = ".mp3"

    def __init__(self, s: Settings):
        if not (s.azure_endpoint and s.azure_api_key):
            raise RuntimeError("Faltan AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_API_KEY (ver .env.example)")
        if not (s.speech_endpoint and s.speech_key):
            raise RuntimeError("Faltan AZURE_SPEECH_ENDPOINT / AZURE_SPEECH_KEY (ver .env.example)")
        self.s = s
        log.info("Proveedor Azure: chat=%s router=%s embeddings=%s | STT=%s TTS=%s | endpoint speech=%s",
                 s.dep_chat, s.dep_router, s.dep_embed, s.stt_modelo, s.speech_voz, s.speech_endpoint)
        self.cliente = AzureOpenAI(
            azure_endpoint=s.azure_endpoint, api_key=s.azure_api_key,
            api_version=s.azure_api_version, timeout=40, max_retries=2,
        )

    def _chat_json(self, tarea, system, payload, modelo):
        deployment = self.s.dep_router if modelo == "router" else self.s.dep_chat
        r = self.cliente.chat.completions.create(
            model=deployment,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)}],
            response_format={"type": "json_object"},
            max_completion_tokens=4000,
        )
        texto = r.choices[0].message.content or "{}"
        uso = Uso(r.usage.prompt_tokens, r.usage.completion_tokens) if r.usage else Uso()
        return json.loads(texto), uso, deployment

    def _speech(self, metodo: str, ruta: str, **kw) -> httpx.Response:
        """Llamada REST a Azure Speech con la clave del recurso; reintenta una vez ante 429/5xx o corte de red."""
        kw["headers"] = {**kw.get("headers", {}), "Ocp-Apim-Subscription-Key": self.s.speech_key}
        ultimo: Exception | None = None
        for intento in (1, 2):
            try:
                r = httpx.request(metodo, f"{self.s.speech_endpoint}{ruta}", timeout=60, **kw)
                if r.status_code in (429, 500, 502, 503, 504) and intento == 1:
                    log.warning("Azure Speech %s respondió %s; se reintenta una vez", ruta, r.status_code)
                    time.sleep(1.5)
                    continue
                r.raise_for_status()
                return r
            except httpx.TransportError as exc:
                ultimo = exc
                log.warning("Azure Speech %s: error de red (%s), intento %d de 2", ruta, type(exc).__name__, intento)
                time.sleep(1.5)
        raise RuntimeError(f"Azure Speech no respondió: {ultimo}")

    def _transcribir(self, ruta: Path) -> str:
        """STT con MAI-Transcribe (Azure Speech, transcripción rápida); el idioma se detecta automáticamente."""
        definicion = json.dumps({"enhancedMode": {"enabled": True, "model": self.s.stt_modelo}})
        mime = mimetypes.guess_type(ruta.name)[0] or "application/octet-stream"
        r = self._speech("POST", f"/speechtotext/transcriptions:transcribe?api-version={self.s.stt_api_version}",
                         files={"audio": (ruta.name, ruta.read_bytes(), mime)}, data={"definition": definicion})
        frases = r.json().get("combinedPhrases") or []
        return " ".join((f.get("text") or "").strip() for f in frases).strip()

    def _extraer_constancia(self, ruta: Path):
        mime = mimetypes.guess_type(ruta.name)[0] or "image/png"
        b64 = base64.b64encode(ruta.read_bytes()).decode()
        r = self.cliente.chat.completions.create(
            model=self.s.dep_chat,
            messages=[
                {"role": "system", "content": cargar_prompt("vision_constancia_v1")},
                {"role": "user", "content": [
                    {"type": "text", "text": "Extrae los campos de esta imagen y responde solo JSON."},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "high"}},
                ]},
            ],
            response_format={"type": "json_object"},
            max_completion_tokens=3000,
        )
        uso = Uso(r.usage.prompt_tokens, r.usage.completion_tokens) if r.usage else Uso()
        return json.loads(r.choices[0].message.content or "{}"), uso, self.s.dep_chat

    def _sintetizar(self, texto: str, destino: Path) -> Path:
        """TTS con MAI-Voice-2 (Azure Speech); la voz es p. ej. `es-ES-Marta:MAI-Voice-2`."""
        ssml = (f"<speak version='1.0' xml:lang='es-ES'><voice name='{self.s.speech_voz}'>"
                f"{xml_escape(texto)}</voice></speak>")
        r = self._speech("POST", "/tts/cognitiveservices/v1", content=ssml.encode("utf-8"),
                         headers={"Content-Type": "application/ssml+xml", "User-Agent": "reclamos-agente",
                                  "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3"})
        destino.write_bytes(r.content)
        return destino

    def _embeber(self, textos: list[str]) -> list[list[float]]:
        r = self.cliente.embeddings.create(model=self.s.dep_embed, input=textos)
        return [d.embedding for d in r.data]
