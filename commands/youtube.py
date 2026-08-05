#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Comando `yt`: descarga videos de YouTube (vía API externa) y los
reenvía por ToDus, con progreso en tiempo real editando el mensaje.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from core import config
from core.context import CommandContext
from core.registry import command

logger = logging.getLogger("bot.commands.youtube")

FORMATS = {"144p", "240p", "360p", "480p", "720p", "1080p", "audio"}

HELP_TEXT = (
    "🎬 Comando yt — Descargar videos de YouTube\n\n"
    f"Uso: yt <url> [formato]\n\n"
    "Formatos: 144p, 240p, 360p, 480p, 720p, 1080p, audio (por defecto 360p)\n\n"
    "Ejemplos:\n"
    "• yt https://youtu.be/dQw4w9WgXcQ\n"
    "• yt https://youtube.com/watch?v=VIDEO 720p\n"
    "• yt https://youtu.be/VIDEO audio\n\n"
    "⚠️ Los videos largos pueden tardar varios minutos."
)


def _is_youtube_url(url: str) -> bool:
    domains = ("youtube.com", "youtu.be", "m.youtube.com", "www.youtube.com")
    return any(d in url.lower() for d in domains)


def _extract_video_id(url: str) -> Optional[str]:
    patterns = [
        r"(?:youtube\.com/watch\?v=)([\w-]+)",
        r"(?:youtu\.be/)([\w-]+)",
        r"(?:youtube\.com/shorts/)([\w-]+)",
        r"(?:m\.youtube\.com/watch\?v=)([\w-]+)",
        r"(?:youtube\.com/embed/)([\w-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def _clean_filename(title: str) -> str:
    filename = re.sub(r'[\\/*?:"<>|]', "", title)
    return filename[:47] + "..." if len(filename) > 50 else filename.strip()


def _format_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _format_time(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m"


def _get_video_info(url: str, fmt: str) -> Optional[Dict[str, Any]]:
    try:
        resp = requests.get(config.YT_API_BASE_URL, params={"url": url, "format": fmt}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("status"):
            logger.error("La API de YouTube devolvió un error: %s", data)
            return None
        return data.get("data", {})
    except requests.RequestException:
        logger.exception("Error de red consultando la API de YouTube.")
        return None
    except ValueError:
        logger.exception("Respuesta JSON inválida de la API de YouTube.")
        return None


def _download_with_progress(download_url: str, filename: str, on_progress) -> Optional[Path]:
    filepath = config.YOUTUBE_FOLDER / filename
    try:
        resp = requests.get(download_url, stream=True, timeout=120)
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        downloaded = 0
        start = time.time()
        last_update = 0.0

        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)
                now = time.time()
                if now - last_update >= 0.5:
                    last_update = now
                    if on_progress:
                        on_progress(downloaded, total, now - start)

        return filepath
    except Exception:
        logger.exception("Error descargando el video de YouTube.")
        return None


def _progress_bar(progress: float, length: int = 20) -> str:
    filled = int(progress / 100 * length)
    return "█" * filled + "░" * (length - filled)


@command("yt", help="Descarga un video de YouTube y te lo envía", usage="yt <url> [formato]")
def handle_yt(ctx: CommandContext) -> None:
    if not ctx.args:
        ctx.reply(HELP_TEXT)
        return

    url = ctx.args[0]
    fmt = "360p"
    if len(ctx.args) >= 2 and ctx.args[1].lower() in FORMATS:
        fmt = ctx.args[1].lower()

    if not _is_youtube_url(url):
        ctx.reply_error("Esa URL no parece ser de YouTube.")
        return

    video_id = _extract_video_id(url)
    if not video_id:
        ctx.reply_error("No se pudo extraer el ID del video de esa URL.")
        return

    msg_id = ctx.reply(f"🎬 Iniciando descarga\n\nID: {video_id}\nFormato: {fmt}\n\n⏳ Obteniendo información...")

    video_info = _get_video_info(url, fmt)
    if not video_info:
        ctx.edit("❌ No se pudo obtener información del video. Verifica la URL.", msg_id)
        return

    title = video_info.get("title", "Video")
    author = video_info.get("author", "Desconocido")
    download_url = video_info.get("download", "")

    if not download_url:
        ctx.edit(f"❌ El video '{title}' no tiene una URL de descarga disponible.", msg_id)
        return

    filename = f"{_clean_filename(title)}.{'mp3' if fmt == 'audio' else 'mp4'}"

    def on_download_progress(downloaded, total, elapsed):
        if total <= 0:
            return
        progress = downloaded / total * 100
        speed = downloaded / elapsed if elapsed > 0 else 0
        text = (
            f"📥 Descargando: {title}\n"
            f"[{_progress_bar(progress)}] {progress:.1f}%\n"
            f"{_format_size(downloaded)} / {_format_size(total)}  ({_format_size(speed)}/s)"
        )
        ctx.edit(text, msg_id)

    download_start = time.time()
    filepath = _download_with_progress(download_url, filename, on_download_progress)
    if not filepath:
        ctx.edit(f"❌ Error al descargar '{title}'. Intenta con otro formato.", msg_id)
        return
    download_time = time.time() - download_start

    ctx.edit(f"📤 Subiendo '{filename}' a ToDus...", msg_id)

    try:
        with open(filepath, "rb") as f:
            file_data = f.read()

        file_type = 3 if fmt != "audio" else 2  # VIDEO o AUDIO

        upload_start = time.time()

        def on_upload_progress(sent, total):
            elapsed = time.time() - upload_start
            progress = (sent / total * 100) if total else 0
            speed = sent / elapsed if elapsed > 0 else 0
            text = (
                f"📤 Subiendo: {title}\n"
                f"[{_progress_bar(progress)}] {progress:.1f}%\n"
                f"{_format_size(sent)} / {_format_size(total)}  ({_format_size(speed)}/s)"
            )
            ctx.edit(text, msg_id)

        upload_url = ctx.client.upload_file(
            file_data, file_type=file_type, file_name=filename, progress_callback=on_upload_progress
        )
        upload_time = time.time() - upload_start

        if fmt != "audio":
            ctx.client.send_video_message(
                to_phone=ctx.sender_phone,
                url=upload_url,
                video_id=video_id,
                file_name=filename,
                file_size=len(file_data),
                duration=0,
                width=0,
                height=0,
                thumbnail="",
                info_text=f"🎬 {title}\n👤 {author}",
            )
        else:
            ctx.client.send_file_message(
                to_phone=ctx.sender_phone,
                url=upload_url,
                file_type=2,
                caption=f"🎵 {title}\n👤 {author}",
                file_name=filename,
                file_size=len(file_data),
            )

        total_time = download_time + upload_time
        ctx.edit(
            f"✅ Video enviado\n\n{title}\n{author}\n"
            f"{_format_size(len(file_data))} en {_format_time(total_time)}",
            msg_id,
        )

    except Exception as exc:
        logger.exception("Error enviando el video a %s", ctx.sender_phone)
        ctx.edit(f"❌ Error al enviar el video: {exc}", msg_id)
    finally:
        try:
            filepath.unlink(missing_ok=True)
        except Exception:
            pass


@command("ythelp", hidden=True, help="Ayuda del comando yt")
def handle_yt_help(ctx: CommandContext) -> None:
    ctx.reply(HELP_TEXT)
