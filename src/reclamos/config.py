"""Configuración centralizada (variables de entorno). Se lee en cada llamada para facilitar pruebas."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[2]
load_dotenv(RAIZ / ".env")

AGENTE_VERSION = "1.0.0"


def _bool(valor: str | None, defecto: bool = False) -> bool:
    if valor is None or valor == "":
        return defecto
    return valor.strip().lower() in {"1", "true", "yes", "si", "sí"}


@dataclass(frozen=True)
class Settings:
    caso_id: str
    semilla: int
    proveedor: str  # "azure" | "mock"
    azure_endpoint: str
    azure_api_key: str
    azure_api_version: str
    dep_chat: str
    dep_router: str
    dep_stt: str
    dep_tts: str
    dep_embed: str
    tts_voz: str
    sql_server: str
    sql_database: str
    sql_user: str
    sql_password: str
    sql_driver: str
    sql_trusted: bool
    qdrant_url: str
    qdrant_path: str
    qdrant_coleccion: str
    otel_endpoint: str
    evidencia_dir: Path
    smtp_host: str
    smtp_port: int
    operador_email: str
    hitl_timeout_horas: float
    max_upload_mb: int
    demo_mode: bool
    mcp_transport: str  # "stdio" | "inproc"
    precio_in_1k: float
    precio_out_1k: float

    def sql_conn_str(self) -> str:
        partes = [
            f"DRIVER={{{self.sql_driver}}}",
            f"SERVER={self.sql_server}",
            f"DATABASE={self.sql_database}",
        ]
        if self.sql_trusted:
            partes += ["Trusted_Connection=yes", "Encrypt=no"]
        else:
            partes += [
                f"UID={self.sql_user}",
                f"PWD={self.sql_password}",
                "Encrypt=yes",
                "TrustServerCertificate=no",
            ]
        partes.append("Connection Timeout=20")
        return ";".join(partes) + ";"


def get_settings() -> Settings:
    e = os.environ.get
    evidencia = Path(e("EVIDENCIA_DIR", str(RAIZ / "evidencia")))
    if not evidencia.is_absolute():
        evidencia = RAIZ / evidencia
    return Settings(
        caso_id=e("CASO_ID", "C-07"),
        semilla=int(e("SEMILLA", "4213")),
        proveedor=e("PROVEEDOR_IA", "azure").lower(),
        azure_endpoint=e("AZURE_OPENAI_ENDPOINT", ""),
        azure_api_key=e("AZURE_OPENAI_API_KEY", ""),
        azure_api_version=e("AZURE_OPENAI_API_VERSION", "2024-10-21"),
        dep_chat=e("AZURE_OPENAI_DEPLOYMENT_CHAT", "gpt-4o"),
        dep_router=e("AZURE_OPENAI_DEPLOYMENT_ROUTER", "gpt-4o-mini"),
        dep_stt=e("AZURE_OPENAI_DEPLOYMENT_STT", "whisper"),
        dep_tts=e("AZURE_OPENAI_DEPLOYMENT_TTS", "tts"),
        dep_embed=e("AZURE_OPENAI_DEPLOYMENT_EMBED", "text-embedding-3-small"),
        tts_voz=e("TTS_VOZ", "alloy"),
        sql_server=e("AZURE_SQL_SERVER", ""),
        sql_database=e("AZURE_SQL_DATABASE", "reclamos"),
        sql_user=e("AZURE_SQL_USER", ""),
        sql_password=e("AZURE_SQL_PASSWORD", ""),
        sql_driver=e("AZURE_SQL_DRIVER", "ODBC Driver 18 for SQL Server"),
        sql_trusted=_bool(e("AZURE_SQL_TRUSTED"), False),
        qdrant_url=e("QDRANT_URL", ""),
        qdrant_path=e("QDRANT_PATH", str(RAIZ / ".qdrant_local")),
        qdrant_coleccion=e("QDRANT_COLECCION", "politicas_reclamacion"),
        otel_endpoint=e("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
        evidencia_dir=evidencia,
        smtp_host=e("SMTP_HOST", ""),
        smtp_port=int(e("SMTP_PORT", "1025")),
        operador_email=e("OPERADOR_EMAIL", "operador@ejemplo.test"),
        hitl_timeout_horas=float(e("HITL_TIMEOUT_HORAS", "24")),
        max_upload_mb=int(e("MAX_UPLOAD_MB", "5")),
        demo_mode=_bool(e("DEMO_MODE"), False),
        mcp_transport=e("MCP_TRANSPORT", "stdio").lower(),
        precio_in_1k=float(e("PRECIO_USD_1K_TOKENS_IN", "0.0025")),
        precio_out_1k=float(e("PRECIO_USD_1K_TOKENS_OUT", "0.01")),
    )
