"""Proveedor Azure OpenAI: chat+visión (gpt-4o), router (gpt-4o-mini), STT, TTS y embeddings."""
from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path

from openai import AzureOpenAI

from ..agente.instrucciones import cargar_prompt
from ..config import Settings
from .interfaces import ProveedorIA, Uso


class ProveedorAzure(ProveedorIA):
    nombre = "azure"
    extension_audio = ".mp3"

    def __init__(self, s: Settings):
        if not (s.azure_endpoint and s.azure_api_key):
            raise RuntimeError("Faltan AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_API_KEY (ver .env.example)")
        self.s = s
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

    def _transcribir(self, ruta: Path) -> str:
        with ruta.open("rb") as f:
            r = self.cliente.audio.transcriptions.create(model=self.s.dep_stt, file=(ruta.name, f.read()),
                                                         language="es")
        return (r.text or "").strip()

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
        r = self.cliente.audio.speech.create(model=self.s.dep_tts, voice=self.s.tts_voz, input=texto,
                                             response_format="mp3")
        destino.write_bytes(r.content)
        return destino

    def _embeber(self, textos: list[str]) -> list[list[float]]:
        r = self.cliente.embeddings.create(model=self.s.dep_embed, input=textos)
        return [d.embedding for d in r.data]
