#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Comando para descargar y enviar videos de YouTube con progreso en tiempo real.
"""

import os
import re
import logging
import time
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

# Configuración
API_BASE_URL = "https://api.delirius.store/download/ytmp4"
DOWNLOAD_FOLDER = Path("downloads/youtube")
DOWNLOAD_FOLDER.mkdir(parents=True, exist_ok=True)

# Formatos disponibles
FORMATS = {
    "144p": "144p",
    "240p": "240p", 
    "360p": "360p",
    "480p": "480p",
    "720p": "720p",
    "1080p": "1080p",
    "audio": "audio",  # Solo audio
}


def extract_video_id(url: str) -> Optional[str]:
    """Extrae el ID del video de una URL de YouTube."""
    patterns = [
        r'(?:youtube\.com\/watch\?v=)([\w-]+)',
        r'(?:youtu\.be\/)([\w-]+)',
        r'(?:youtube\.com\/shorts\/)([\w-]+)',
        r'(?:m\.youtube\.com\/watch\?v=)([\w-]+)',
        r'(?:youtube\.com\/embed\/)([\w-]+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    
    return None


def is_youtube_url(url: str) -> bool:
    """Verifica si una URL es de YouTube."""
    youtube_domains = [
        'youtube.com',
        'youtu.be',
        'm.youtube.com',
        'www.youtube.com',
    ]
    return any(domain in url.lower() for domain in youtube_domains)


def format_size(bytes_size: int) -> str:
    """Formatea el tamaño en bytes a formato legible."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_size < 1024:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024
    return f"{bytes_size:.1f} TB"


def format_time(seconds: int) -> str:
    """Formatea segundos a formato legible."""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes}m {secs}s"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}h {minutes}m"


def get_video_info(url: str, format: str = "360p") -> Optional[Dict[str, Any]]:
    """Obtiene información del video usando la API."""
    try:
        api_url = f"{API_BASE_URL}?url={url}&format={format}"
        logger.info(f"📡 Consultando API: {api_url}")
        
        response = requests.get(api_url, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        
        if not data.get('status'):
            logger.error(f"❌ API devolvió error: {data}")
            return None
        
        return data.get('data', {})
        
    except requests.exceptions.Timeout:
        logger.error("❌ Timeout al consultar la API")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Error al consultar la API: {e}")
        return None
    except ValueError as e:
        logger.error(f"❌ Error al parsear respuesta JSON: {e}")
        return None


def download_video_with_progress(download_url: str, filename: str, progress_callback=None) -> Optional[Path]:
    """
    Descarga un video desde una URL con callback de progreso.
    
    Args:
        download_url: URL de descarga
        filename: Nombre del archivo
        progress_callback: Función que recibe (descargado, total)
    
    Returns:
        Path al archivo descargado o None si falla
    """
    try:
        filepath = DOWNLOAD_FOLDER / filename
        
        logger.info(f"📥 Descargando video: {filename}")
        
        response = requests.get(download_url, stream=True, timeout=120)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0
        start_time = time.time()
        last_update = 0
        
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    
                    # Actualizar progreso cada 0.5 segundos
                    current_time = time.time()
                    if current_time - last_update >= 0.5:
                        last_update = current_time
                        if progress_callback:
                            progress_callback(downloaded, total_size, current_time - start_time)
        
        logger.info(f"✅ Video descargado: {filepath} ({downloaded} bytes)")
        return filepath
        
    except Exception as e:
        logger.error(f"❌ Error descargando video: {e}")
        return None


def clean_filename(title: str) -> str:
    """Limpia un título para usarlo como nombre de archivo."""
    filename = re.sub(r'[\\/*?:"<>|]', '', title)
    if len(filename) > 50:
        filename = filename[:47] + "..."
    return filename.strip()


def update_progress_message(client, to_phone: str, msg_id: str, step: str, progress: float = 0, 
                           details: dict = None):
    """
    Actualiza un mensaje de progreso.
    
    Args:
        client: Cliente ToDus
        to_phone: Número del destinatario
        msg_id: ID del mensaje a editar
        step: Paso actual ('info', 'downloading', 'uploading', 'complete', 'error')
        progress: Progreso (0-100)
        details: Detalles adicionales
    """
    emojis = {
        'info': '🔍',
        'downloading': '📥',
        'uploading': '📤',
        'complete': '✅',
        'error': '❌',
        'processing': '⚙️'
    }
    
    emoji = emojis.get(step, '📌')
    
    # Construir barra de progreso
    bar_length = 20
    filled = int(progress / 100 * bar_length)
    bar = '█' * filled + '░' * (bar_length - filled)
    
    if details is None:
        details = {}
    
    # Mensaje base
    if step == 'info':
        message = (
            f"{emoji} **{details.get('title', 'Procesando')}**\n\n"
            f"{details.get('message', '')}\n\n"
            f"⏳ Por favor espera..."
        )
    
    elif step == 'downloading':
        elapsed = details.get('elapsed', 0)
        speed = details.get('speed', 0)
        downloaded = details.get('downloaded', 0)
        total = details.get('total', 0)
        
        message = (
            f"📥 **Descargando video**\n\n"
            f"📌 {details.get('title', 'Video')}\n"
            f"📹 Formato: {details.get('format', '360p')}\n\n"
            f"`[{bar}]`\n"
            f"**{progress:.1f}%** completado\n\n"
            f"📦 {format_size(downloaded)} / {format_size(total)}\n"
            f"⚡ {format_size(speed)}/s\n"
            f"⏱️ {format_time(elapsed)}\n\n"
            f"⏳ Descargando... {progress:.1f}%"
        )
    
    elif step == 'uploading':
        elapsed = details.get('elapsed', 0)
        speed = details.get('speed', 0)
        uploaded = details.get('uploaded', 0)
        total = details.get('total', 0)
        
        message = (
            f"📤 **Subiendo a ToDus**\n\n"
            f"📌 {details.get('title', 'Video')}\n"
            f"📹 Formato: {details.get('format', '360p')}\n\n"
            f"`[{bar}]`\n"
            f"**{progress:.1f}%** completado\n\n"
            f"📦 {format_size(uploaded)} / {format_size(total)}\n"
            f"⚡ {format_size(speed)}/s\n"
            f"⏱️ {format_time(elapsed)}\n\n"
            f"⏳ Subiendo a ToDus... {progress:.1f}%"
        )
    
    elif step == 'complete':
        total_size = details.get('size', 0)
        total_time = details.get('time', 0)
        
        message = (
            f"✅ **Video enviado correctamente**\n\n"
            f"📌 {details.get('title', 'Video')}\n"
            f"👤 {details.get('author', 'Desconocido')}\n"
            f"📹 Formato: {details.get('format', '360p')}\n"
            f"📦 {format_size(total_size)}\n"
            f"⏱️ Tiempo total: {format_time(total_time)}\n\n"
            f"🎬 ¡Disfruta tu video!"
        )
    
    elif step == 'error':
        message = (
            f"❌ **Error**\n\n"
            f"{details.get('message', 'Ocurrió un error inesperado')}\n\n"
            f"📌 {details.get('title', '')}\n"
            f"🔧 Intenta con otro formato o verifica la URL."
        )
    
    else:  # processing
        message = f"{emoji} {details.get('message', 'Procesando...')}"
    
    try:
        # Editar el mensaje existente
        client.edit_message(to_phone, message, msg_id)
        logger.debug(f"📝 Mensaje actualizado: {msg_id} - {step} - {progress:.1f}%")
    except Exception as e:
        logger.error(f"❌ Error actualizando mensaje: {e}")


def handle_yt(client, message: dict):
    """
    Maneja el comando 'yt' - Descarga y envía videos de YouTube.
    """
    sender = message.get('from')
    if not sender:
        return
    
    sender_phone = sender.split('@')[0]
    body = message.get('body', '').strip()
    
    # Extraer URL y formato
    parts = body.split()
    if len(parts) < 2:
        help_message = (
            f"🎬 **Comando yt - Descargar videos de YouTube**\n\n"
            f"Uso: `yt <url> [formato]`\n\n"
            f"📌 **Ejemplos:**\n"
            f"• `yt https://youtu.be/VIDEO` - Descarga en 360p\n"
            f"• `yt https://youtube.com/watch?v=VIDEO 720p`\n\n"
            f"📋 **Formatos:** 144p, 240p, 360p, 480p, 720p, 1080p, audio\n\n"
            f"⚠️ Videos largos pueden tardar varios minutos."
        )
        client.send_message(sender_phone, help_message)
        return
    
    # Extraer URL y formato
    url = parts[1]
    format = "360p"
    if len(parts) >= 3:
        format_candidate = parts[2].lower()
        if format_candidate in FORMATS:
            format = FORMATS[format_candidate]
    
    # Validar URL
    if not is_youtube_url(url):
        error_msg = "❌ **URL no válida**\n\nNo parece ser una URL de YouTube."
        client.send_message(sender_phone, error_msg)
        return
    
    video_id = extract_video_id(url)
    if not video_id:
        error_msg = "❌ No se pudo extraer el ID del video."
        client.send_message(sender_phone, error_msg)
        return
    
    try:
        # Enviar mensaje inicial
        initial_msg = (
            f"🎬 **Iniciando descarga**\n\n"
            f"ID: `{video_id}`\n"
            f"Formato: `{format}`\n\n"
            f"⏳ Obteniendo información del video..."
        )
        msg_id = client.send_message(sender_phone, initial_msg)
        
        # --- PASO 1: Obtener información del video ---
        update_progress_message(
            client, sender_phone, msg_id,
            step='processing',
            details={'message': '🔍 Obteniendo información del video...'}
        )
        
        video_info = get_video_info(url, format)
        
        if not video_info:
            update_progress_message(
                client, sender_phone, msg_id,
                step='error',
                details={
                    'message': 'No se pudo obtener información del video.\nVerifica la URL.',
                    'title': video_id
                }
            )
            return
        
        title = video_info.get('title', 'Video')
        author = video_info.get('author', 'Desconocido')
        download_url = video_info.get('download', '')
        
        if not download_url:
            update_progress_message(
                client, sender_phone, msg_id,
                step='error',
                details={
                    'message': 'URL de descarga no encontrada.\nEl video no está disponible.',
                    'title': title
                }
            )
            return
        
        # --- PASO 2: Descargar el video ---
        filename = f"{clean_filename(title)}.mp4" if format != "audio" else f"{clean_filename(title)}.mp3"
        
        # Variables para el progreso
        download_start_time = time.time()
        download_details = {
            'title': title,
            'format': format,
            'downloaded': 0,
            'total': 0,
            'speed': 0,
            'elapsed': 0
        }
        
        def progress_callback(downloaded, total, elapsed):
            if total > 0:
                progress = (downloaded / total) * 100
                speed = downloaded / elapsed if elapsed > 0 else 0
                
                download_details.update({
                    'downloaded': downloaded,
                    'total': total,
                    'speed': speed,
                    'elapsed': elapsed
                })
                
                update_progress_message(
                    client, sender_phone, msg_id,
                    step='downloading',
                    progress=progress,
                    details=download_details
                )
        
        # Iniciar descarga
        filepath = download_video_with_progress(download_url, filename, progress_callback)
        
        if not filepath:
            update_progress_message(
                client, sender_phone, msg_id,
                step='error',
                details={
                    'message': 'Error al descargar el video.\nIntenta con otro formato.',
                    'title': title
                }
            )
            return
        
        download_time = time.time() - download_start_time
        
        # --- PASO 3: Subir y enviar el video ---
        update_progress_message(
            client, sender_phone, msg_id,
            step='processing',
            details={'message': f'📤 Subiendo {filename} a ToDus...'}
        )
        
        try:
            with open(filepath, 'rb') as f:
                file_data = f.read()
            
            file_type = 3 if format != "audio" else 2  # VIDEO o AUDIO
            
            # Subir archivo con progreso
            upload_start_time = time.time()
            upload_details = {
                'title': title,
                'format': format,
                'uploaded': 0,
                'total': len(file_data),
                'speed': 0,
                'elapsed': 0
            }
            
            def upload_progress_callback(sent, total):
                elapsed = time.time() - upload_start_time
                progress = (sent / total) * 100 if total > 0 else 0
                speed = sent / elapsed if elapsed > 0 else 0
                
                upload_details.update({
                    'uploaded': sent,
                    'total': total,
                    'speed': speed,
                    'elapsed': elapsed
                })
                
                update_progress_message(
                    client, sender_phone, msg_id,
                    step='uploading',
                    progress=progress,
                    details=upload_details
                )
            
            # Subir a ToDus
            url_upload = client.upload_file(
                file_data,
                file_type=file_type,
                file_name=filename,
                progress_callback=upload_progress_callback
            )
            
            upload_time = time.time() - upload_start_time
            
            # Enviar mensaje con el archivo
            if format != "audio":
                caption = f"🎬 **{title}**\n👤 {author}"
                client.send_video_message(
                    to_phone=sender_phone,
                    url=url_upload,
                    video_id=video_id,
                    file_name=filename,
                    file_size=len(file_data),
                    duration=0,
                    width=0,
                    height=0,
                    thumbnail="",
                    info_text=caption
                )
            else:
                caption = f"🎵 **{title}**\n👤 {author}"
                client.send_file_message(
                    to_phone=sender_phone,
                    url=url_upload,
                    file_type=2,
                    caption=caption,
                    file_name=filename,
                    file_size=len(file_data)
                )
            
            # --- PASO 4: Confirmación final ---
            total_time = download_time + upload_time
            update_progress_message(
                client, sender_phone, msg_id,
                step='complete',
                details={
                    'title': title,
                    'author': author,
                    'format': format,
                    'size': len(file_data),
                    'time': total_time
                }
            )
            
            logger.info(f"✅ Video enviado a {sender_phone}: {filename}")
            
            # Limpiar archivo temporal
            try:
                filepath.unlink()
            except:
                pass
            
        except Exception as e:
            logger.error(f"❌ Error enviando video: {e}")
            update_progress_message(
                client, sender_phone, msg_id,
                step='error',
                details={
                    'message': f'Error al enviar: {str(e)}',
                    'title': title
                }
            )
            
    except Exception as e:
        logger.error(f"❌ Error en handle_yt: {e}")
        client.send_message(
            sender_phone,
            f"❌ **Error inesperado**\n\n{str(e)}"
        )


def handle_yt_help(client, message: dict):
    """Envía ayuda sobre el comando yt."""
    sender = message.get('from')
    if not sender:
        return
    
    sender_phone = sender.split('@')[0]
    
    help_message = (
        f"🎬 **Comando yt - Descargar videos de YouTube**\n\n"
        f"📌 **Uso:**\n"
        f"`yt <url> [formato]`\n\n"
        f"📋 **Formatos disponibles:**\n"
        f"• `144p` - Baja calidad\n"
        f"• `240p` - Calidad baja\n"
        f"• `360p` - Calidad media (por defecto)\n"
        f"• `480p` - Calidad media-alta\n"
        f"• `720p` - HD\n"
        f"• `1080p` - Full HD\n"
        f"• `audio` - Solo audio (MP3)\n\n"
        f"📌 **Ejemplos:**\n"
        f"• `yt https://youtu.be/dQw4w9WgXcQ`\n"
        f"• `yt https://youtube.com/watch?v=VIDEO 720p`\n"
        f"• `yt https://youtu.be/VIDEO audio`\n\n"
        f"📊 **Estado en tiempo real:**\n"
        f"• Barra de progreso\n"
        f"• Velocidad de descarga\n"
        f"• Tiempo estimado\n"
        f"• Tamaño del archivo\n\n"
        f"⚠️ Videos largos pueden tardar varios minutos."
    )
    
    try:
        client.send_message(sender_phone, help_message)
        logger.info(f"✅ Ayuda de yt enviada a {sender_phone}")
    except Exception as e:
        logger.error(f"❌ Error enviando ayuda de yt: {e}")