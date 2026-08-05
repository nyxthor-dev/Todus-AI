#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Configuración de logging con "consola limpia".

Filosofía:
- La consola (stdout) solo muestra WARNING y ERROR (configurable),
  para que el operador del bot vea de un vistazo si algo anda mal,
  sin ruido de "mensaje recibido de fulano" en cada línea.
- Un archivo de log (bot.log por defecto) guarda todo el detalle
  (INFO/DEBUG incluidos) para poder investigar después.
- Un pequeño helper `console_status(...)` permite imprimir mensajes
  "bonitos" de estado (arranque, comandos cargados, etc.) directo a
  stdout sin pasar por el nivel de logging, para que el arranque del
  bot siga siendo legible incluso con LOG_LEVEL_CONSOLE=WARNING.
"""

import logging
import sys

from . import config


class _ConsoleFormatter(logging.Formatter):
    """Formato compacto y con color simple para consola."""

    COLORS = {
        "WARNING": "\033[33m",   # amarillo
        "ERROR": "\033[31m",     # rojo
        "CRITICAL": "\033[41m",  # fondo rojo
    }
    RESET = "\033[0m"

    def format(self, record):
        base = f"{record.levelname:<8} {record.name}: {record.getMessage()}"
        color = self.COLORS.get(record.levelname)
        if color and sys.stdout.isatty():
            return f"{color}{base}{self.RESET}"
        return base


def setup_logging() -> logging.Logger:
    """Configura el logging raíz y devuelve el logger principal del bot."""
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)  # el filtrado real lo hacen los handlers
    root.handlers.clear()

    # --- Handler de consola: solo warnings/errores ---
    console_level = getattr(logging, config.LOG_LEVEL_CONSOLE, logging.WARNING)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(_ConsoleFormatter())
    root.addHandler(console_handler)

    # --- Handler de archivo: todo el detalle ---
    try:
        file_level = getattr(logging, config.LOG_LEVEL_FILE, logging.INFO)
        file_handler = logging.FileHandler(config.LOG_FILE, encoding="utf-8")
        file_handler.setLevel(file_level)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        root.addHandler(file_handler)
    except OSError:
        # Si no se puede escribir el archivo (permsos, disco de solo lectura, etc.)
        # seguimos solo con consola, pero avisamos por consola con un warning.
        logging.getLogger("bot").warning(
            "No se pudo abrir el archivo de log %s; solo se registrará en consola.",
            config.LOG_FILE,
        )

    # Silenciar librerías ruidosas de terceros en consola (igual quedan en archivo)
    for noisy in ("urllib3", "werkzeug", "requests"):
        logging.getLogger(noisy).setLevel(logging.ERROR)

    return logging.getLogger("bot")


def console_status(message: str) -> None:
    """Imprime una línea de estado directo a stdout.

    Se usa para los mensajes de arranque (banner, comandos cargados,
    prefijos activos, etc.) que queremos que el operador vea siempre,
    independientemente del nivel de log configurado para la consola.
    """
    print(message, flush=True)
