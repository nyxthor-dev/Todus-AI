#!/usr/bin/env python3
"""
Entry point del bot de toDus + IA.

Uso:
    python main.py

Variables de entorno necesarias (ver .env.example):
    TODUS_PHONE, TODUS_PASSWORD, OWNER_PHONE, AI_API_KEY
"""
from __future__ import annotations

import logging
import logging.handlers
import signal
import sys
import time

from bot.config import settings, PROJECT_ROOT
from bot.core import NyxBot


def setup_logging() -> None:
    """Configura logging a archivo (rotativo) + stderr."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    fmt = "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    # Handler a archivo rotativo (5MB x 3 archivos)
    file_handler = logging.handlers.RotatingFileHandler(
        settings.log_file_path, maxBytes=5 * 1024 * 1024, backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(fmt, datefmt))

    # Handler a consola
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)-7s] %(message)s", datefmt))

    root = logging.getLogger()
    root.setLevel(level)
    # Limpiar handlers default
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(file_handler)
    root.addHandler(console)

    # Reducir ruido de librerias externas
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def main() -> int:
    setup_logging()
    log = logging.getLogger("main")

    log.info("=" * 60)
    log.info("NyxBot - toDus + IA")
    log.info("Proyecto: %s", PROJECT_ROOT)
    log.info("Bot phone: %s", settings.todus_phone)
    log.info("Owner:    %s", settings.owner_phone)
    log.info("Modelo IA: %s @ %s", settings.ai_model, settings.ai_api_base)
    log.info("Limites:  privado=%d/min, grupo=%d/min",
             settings.limit_private, settings.limit_group)
    log.info("Memoria:  %s (max %d msgs/usuario)",
             settings.memory_db_path, settings.memory_max_messages)
    log.info("Humano:   typing=%s, stream_edit=%s, online=%s",
             settings.human_typing, settings.human_stream_edit, settings.human_online)
    log.info("=" * 60)

    # Validar config antes de arrancar
    errs = settings.validate()
    if errs:
        for e in errs:
            log.error("Config: %s", e)
        log.error("Edita .env con los valores correctos. Saliendo.")
        return 1

    # Crear bot
    try:
        bot = NyxBot()
    except Exception as e:
        log.exception("No se pudo inicializar el bot: %s", e)
        return 2

    # Capturar senales para apagar graceful
    def _shutdown(signum, frame):
        sig_name = signal.Signals(signum).name
        log.info("Senal %s recibida, deteniendo...", sig_name)
        bot.stop()
        # Dar tiempo a cerrar conexiones
        time.sleep(1)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # Bucle principal con reintentos
    while True:
        try:
            bot.run()
            break
        except KeyboardInterrupt:
            log.info("Interrumpido por teclado")
            break
        except Exception as e:
            log.exception("Bot cayo: %s. Reintentando en 15s", e)
            time.sleep(15)

    log.info("Fin del proceso")
    return 0


if __name__ == "__main__":
    sys.exit(main())
