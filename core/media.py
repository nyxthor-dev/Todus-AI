#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Manejo de multimedia entrante (imágenes, vídeos, archivos, stickers,
contactos, ubicaciones, eventos, audio, notas de voz).

`handle_incoming_media` es llamado por el dispatcher cada vez que
detecta que un mensaje no es texto plano. Por defecto solo confirma
la recepción y muestra los metadatos; si se quiere además descargar
el archivo a disco, usar `download_media`.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from . import config
from .parsing import extract_media_fields

try:
    from todus import util
except ImportError:  # pragma: no cover - solo por robustez si cambia el layout
    util = None

logger = logging.getLogger("bot.media")


def _format_size(num_bytes: int) -> str:
    if util is not None:
        try:
            return util.format_size(num_bytes)
        except Exception:
            pass
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def handle_incoming_media(client, message: dict, media_label: str) -> None:
    """Confirma la recepción de un mensaje multimedia con sus metadatos."""
    sender = message.get("from", "")
    if not sender:
        return
    sender_phone = sender.split("@")[0].split("/")[0]

    raw = message.get("raw", "") or ""
    body = message.get("body", "") or ""
    fields = extract_media_fields(raw)

    file_name = fields.get("file_name", "archivo")
    file_size = fields.get("file_size", 0)

    lines = [f"📥 Recibido: {media_label}", f"📄 Nombre: {file_name}"]
    if file_size:
        lines.append(f"📦 Tamaño: {_format_size(file_size)}")
    if fields.get("width") and fields.get("height"):
        lines.append(f"📐 Dimensiones: {fields['width']}x{fields['height']}")
    if fields.get("duration"):
        lines.append(f"⏱️ Duración: {fields['duration']}s")
    if body:
        lines.append(f"📝 Texto: {body}")

    lines.append("\n✅ Archivo recibido correctamente.")

    try:
        client.send_message(sender_phone, "\n".join(lines))
    except Exception:
        logger.exception("Error respondiendo a multimedia de %s", sender_phone)


def download_media(client, message: dict, folder: Optional[Path] = None) -> Optional[Tuple[str, str]]:
    """Descarga a disco el contenido multimedia de un mensaje, si trae URL.

    Devuelve (ruta_completa, nombre_archivo) o None si no se pudo.
    """
    raw = message.get("raw", "") or ""
    fields = extract_media_fields(raw)
    url = fields.get("url") or message.get("url")
    if not url:
        logger.warning("No se encontró URL para descargar en el mensaje.")
        return None

    file_name = fields.get("file_name", "archivo")
    target_folder = folder or config.MEDIA_FOLDER
    target_folder.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = f"{timestamp}_{file_name}"

    try:
        client.download_file_to_folder(url=url, folder=str(target_folder), filename=safe_name)
        return str(target_folder / safe_name), safe_name
    except Exception:
        logger.exception("Error descargando %s", file_name)
        return None
