"""Carga de instrucciones versionadas del agente (archivos .md en agente/prompts/)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

DIR = Path(__file__).parent / "prompts"


@lru_cache(maxsize=None)
def cargar_prompt(nombre: str) -> str:
    return (DIR / f"{nombre}.md").read_text(encoding="utf-8")
