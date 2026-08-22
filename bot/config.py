"""
Configuracion central del bot.
Lee variables de entorno (.env) y expone un objeto Settings.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Resolver raiz del proyecto (carpeta que contiene este archivo/..)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Cargar .env si existe
_env_path = PROJECT_ROOT / ".env"
if _env_path.exists():
    load_dotenv(_env_path)


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "si", "y"}


def _int(value: str | None, default: int) -> int:
    try:
        return int(value) if value else default
    except (TypeError, ValueError):
        return default


def _float(value: str | None, default: float) -> float:
    try:
        return float(value) if value else default
    except (TypeError, ValueError):
        return default


@dataclass
class Settings:
    # toDus
    todus_phone: str = field(default_factory=lambda: os.getenv("TODUS_PHONE", ""))
    todus_password: str = field(default_factory=lambda: os.getenv("TODUS_PASSWORD", ""))

    # Owner
    owner_phone: str = field(default_factory=lambda: os.getenv("OWNER_PHONE", ""))

    # IA
    ai_api_base: str = field(default_factory=lambda: os.getenv("AI_API_BASE", "https://vimax-ia.p.jo3.org/v1"))
    ai_api_key: str = field(default_factory=lambda: os.getenv("AI_API_KEY", ""))
    ai_model: str = field(default_factory=lambda: os.getenv("AI_MODEL", "gemini-3.5-flash-lite"))

    # Human-like
    human_typing: bool = field(default_factory=lambda: _bool(os.getenv("HUMAN_TYPING"), True))
    human_min_delay: float = field(default_factory=lambda: _float(os.getenv("HUMAN_MIN_DELAY"), 0.8))
    human_stream_edit: bool = field(default_factory=lambda: _bool(os.getenv("HUMAN_STREAM_EDIT"), True))
    human_edit_interval: int = field(default_factory=lambda: _int(os.getenv("HUMAN_EDIT_INTERVAL"), 180))
    human_online: bool = field(default_factory=lambda: _bool(os.getenv("HUMAN_ONLINE"), True))

    # Rate limits
    limit_private: int = field(default_factory=lambda: _int(os.getenv("LIMIT_PRIVATE"), 5))
    limit_group: int = field(default_factory=lambda: _int(os.getenv("LIMIT_GROUP"), 10))

    # Memoria
    memory_max_messages: int = field(default_factory=lambda: _int(os.getenv("MEMORY_MAX_MESSAGES"), 20))
    memory_db: str = field(default_factory=lambda: os.getenv("MEMORY_DB", "data/memory.db"))

    # Logging
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    log_file: str = field(default_factory=lambda: os.getenv("LOG_FILE", "logs/bot.log"))

    # System prompt del bot (personalidad)
    system_prompt: str = (
        "Sos NyxBot, un asistente conversacional que vive dentro de la app de mensajeria toDus. "
        "Te hablan personas comunes desde su telefono, igual que si fuera un chat de WhatsApp/Telegram. "
        "Por eso, tus respuestas tienen que ser NATURALES y HUMANAS, no roboticas:\n"
        "- Escribi en español rioplatense neutro, con voseo suave cuando sea natural.\n"
        "- Frases cortas, sin listas tipo markdown a menos que la respuesta lo justifique.\n"
        "- NO uses asteriscos para acciones ni formateos raros: la otra persona lo ve como texto plano.\n"
        "- Si no sabes algo, decilo sin dar vueltas.\n"
        "- Si te preguntan quien sos, decis que sos NyxBot, un asistente de IA.\n"
        "- Mantene el contexto de la conversacion anterior del usuario.\n"
        "- Si el mensaje parece un comando (empieza con /), no respondas: ya lo maneja el sistema.\n"
        "- Optimiza para claridad y rapidez: la persona esta esperando una respuesta en su telefono."
    )

    @property
    def memory_db_path(self) -> Path:
        p = Path(self.memory_db)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def log_file_path(self) -> Path:
        p = Path(self.log_file)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def validate(self) -> list[str]:
        """Devuelve lista de errores de configuracion (vacia si todo OK)."""
        errs = []
        if not self.todus_phone:
            errs.append("TODUS_PHONE no configurado")
        if not self.todus_password:
            errs.append("TODUS_PASSWORD no configurado")
        if not self.ai_api_key:
            errs.append("AI_API_KEY no configurado")
        if not self.owner_phone:
            errs.append("OWNER_PHONE no configurado")
        return errs


# Singleton
settings = Settings()
