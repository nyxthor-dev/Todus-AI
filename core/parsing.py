#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Utilidades de parseo: detectar prefijo/comando en texto y detectar
si un mensaje entrante es multimedia (imagen, video, sticker, etc.).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from . import config

# Tipos de stanza multimedia que puede traer ToDus en el XML crudo,
# mapeados a una etiqueta legible para humanos.
MEDIA_TAGS = {
    "image": "📷 Imagen",
    "video": "🎬 Vídeo",
    "sticker": "🏷️ Sticker",
    "contact": "👤 Contacto",
    "file": "📎 Archivo",
    "location": "📍 Ubicación",
    "event": "📅 Evento",
    "audio": "🎵 Audio",
    "voice": "🎙️ Nota de voz",
}


@dataclass
class ParsedCommand:
    command: str
    args: list
    raw_args: str


def parse_command(body: str) -> Optional[ParsedCommand]:
    """Intenta interpretar `body` como una invocación de comando.

    Reconoce cualquiera de los prefijos configurados en config.PREFIXES.
    Si config.ALLOW_NO_PREFIX está activo, también acepta el texto sin
    prefijo. Devuelve None si el texto no corresponde a un comando.
    """
    text = (body or "").strip()
    if not text:
        return None

    matched = False
    rest = text
    for prefix in config.PREFIXES:
        if text.startswith(prefix):
            rest = text[len(prefix):]
            matched = True
            break

    if not matched:
        if not config.ALLOW_NO_PREFIX:
            return None
        rest = text

    rest = rest.strip()
    if not rest:
        return None

    parts = rest.split(maxsplit=1)
    cmd_name = parts[0].lower()
    raw_args = parts[1] if len(parts) > 1 else ""
    args = raw_args.split() if raw_args else []

    return ParsedCommand(command=cmd_name, args=args, raw_args=raw_args)


def detect_media_type(message: dict) -> Optional[str]:
    """Devuelve la etiqueta legible del tipo de multimedia, o None si es texto plano."""
    raw = message.get("raw", "") or ""
    for tag, label in MEDIA_TAGS.items():
        if f"<{tag}" in raw:
            return label

    # Señales adicionales por si el SDK ya normalizó el mensaje
    if message.get("url") or message.get("file_id") or message.get("video_url") or message.get("sticker_id"):
        return "📎 Archivo"

    return None


def extract_media_fields(raw: str) -> dict:
    """Extrae campos comunes (nombre, tamaño, url, dimensiones, duración) del XML crudo."""
    info = {}

    name_match = re.search(r"n='([^']*)'", raw)
    if name_match:
        info["file_name"] = name_match.group(1)

    size_match = re.search(r"s='([^']*)'", raw)
    if size_match:
        try:
            info["file_size"] = int(size_match.group(1))
        except ValueError:
            pass

    url_match = re.search(r"url='([^']*)'", raw)
    if url_match:
        info["url"] = url_match.group(1)

    w_match = re.search(r"w='([^']*)'", raw)
    h_match = re.search(r"he='([^']*)'", raw)
    if w_match and h_match:
        try:
            info["width"] = int(w_match.group(1))
            info["height"] = int(h_match.group(1))
        except ValueError:
            pass

    d_match = re.search(r"d='([^']*)'", raw)
    if d_match:
        try:
            info["duration"] = int(d_match.group(1))
        except ValueError:
            pass

    return info
