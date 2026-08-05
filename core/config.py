#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Configuración central del bot.

Todo lo configurable vive aquí: prefijos de comandos, credenciales,
rutas de descarga y opciones del anti-spam. Se lee desde variables
de entorno (.env) con valores por defecto sensatos.
"""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent

# ------------------------------------------------------------------
# Credenciales de la cuenta ToDus
# ------------------------------------------------------------------
PHONE_NUMBER = os.getenv("PHONE_NUMBER", "")
PASSWORD = os.getenv("PASSWORD", "")

# ------------------------------------------------------------------
# Prefijos de comandos
# ------------------------------------------------------------------
# Se acepta uno o varios prefijos separados por coma en PREFIXES,
# por ejemplo: PREFIXES="!,/,." Si no hay prefijo configurado, se usa "!".
# Si ALLOW_NO_PREFIX es "true", los comandos también se reconocen sin
# prefijo (por ejemplo "start" además de "!start").
_raw_prefixes = os.getenv("PREFIXES", "!")
PREFIXES = [p for p in (p.strip() for p in _raw_prefixes.split(",")) if p]
if not PREFIXES:
    PREFIXES = ["!"]

ALLOW_NO_PREFIX = os.getenv("ALLOW_NO_PREFIX", "false").strip().lower() == "true"

# ------------------------------------------------------------------
# Carpetas
# ------------------------------------------------------------------
DOWNLOAD_FOLDER = Path(os.getenv("DOWNLOAD_FOLDER", str(BASE_DIR / "downloads")))
YOUTUBE_FOLDER = DOWNLOAD_FOLDER / "youtube"
MEDIA_FOLDER = DOWNLOAD_FOLDER / "media"
COMMANDS_FOLDER = BASE_DIR / "commands"

for _folder in (DOWNLOAD_FOLDER, YOUTUBE_FOLDER, MEDIA_FOLDER):
    _folder.mkdir(parents=True, exist_ok=True)

# ------------------------------------------------------------------
# Anti-spam
# ------------------------------------------------------------------
ANTISPAM_MAX_CACHE = int(os.getenv("ANTISPAM_MAX_CACHE", "2000"))
ANTISPAM_COOLDOWN_SECONDS = float(os.getenv("ANTISPAM_COOLDOWN_SECONDS", "2"))

# ------------------------------------------------------------------
# Flask (health check)
# ------------------------------------------------------------------
PORT = int(os.getenv("PORT", "8080"))
ENABLE_FLASK = os.getenv("ENABLE_FLASK", "true").strip().lower() == "true"

# ------------------------------------------------------------------
# Consola / logging
# ------------------------------------------------------------------
# LOG_LEVEL controla qué se imprime en consola. Por defecto solo
# se muestran advertencias y errores para mantener la consola limpia;
# la actividad normal (mensajes, comandos ejecutados) se guarda en el
# archivo de log pero no ensucia la terminal.
LOG_LEVEL_CONSOLE = os.getenv("LOG_LEVEL_CONSOLE", "WARNING").upper()
LOG_LEVEL_FILE = os.getenv("LOG_LEVEL_FILE", "INFO").upper()
LOG_FILE = os.getenv("LOG_FILE", str(BASE_DIR / "bot.log"))

# APIs externas usadas por comandos incluidos
YT_API_BASE_URL = os.getenv("YT_API_BASE_URL", "https://api.delirius.store/download/ytmp4")
DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL", "https://ds-flaskapi.onrender.com")
