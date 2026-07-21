#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Manejador de mensajes multimedia (imágenes, vídeos, archivos).
"""

import os
import logging
import re
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class MediaHandler:
    """
    Clase para manejar mensajes multimedia.
    """
    
    def __init__(self, client, download_folder: str = "downloads"):
        self.client = client
        self.download_folder = Path(download_folder)
        self.download_folder.mkdir(parents=True, exist_ok=True)
        logger.info(f"📁 Carpeta de descargas: {self.download_folder}")
    
    def extract_media_info(self, message: dict) -> dict:
        """
        Extrae información de un mensaje multimedia usando el raw XML.
        """
        raw = message.get('raw', '')
        body = message.get('body', '')
        
        info = {
            'type': 'unknown',
            'file_name': 'archivo',
            'file_size': 0,
            'caption': body,
            'url': message.get('url', ''),
            'file_id': message.get('file_id', ''),
            'video_id': message.get('video_id', ''),
            'sticker_id': message.get('sticker_id', ''),
            'contact_id': message.get('contact_id', ''),
        }
        
        # Detectar tipo por el raw
        if '<image' in raw:
            info['type'] = 'image'
        elif '<video' in raw:
            info['type'] = 'video'
        elif '<sticker' in raw:
            info['type'] = 'sticker'
        elif '<contact' in raw:
            info['type'] = 'contact'
        elif '<file' in raw:
            info['type'] = 'file'
        elif '<location' in raw:
            info['type'] = 'location'
        elif '<event' in raw:
            info['type'] = 'event'
        
        # Extraer nombre de archivo
        name_match = re.search(r"n='([^']*)'", raw)
        if name_match:
            info['file_name'] = name_match.group(1)
        
        # Extraer tamaño
        size_match = re.search(r"s='([^']*)'", raw)
        if size_match:
            try:
                info['file_size'] = int(size_match.group(1))
            except:
                pass
        
        # Extraer URL
        url_match = re.search(r"url='([^']*)'", raw)
        if url_match:
            info['url'] = url_match.group(1)
        
        # Extraer dimensiones (imagen/video)
        w_match = re.search(r"w='([^']*)'", raw)
        h_match = re.search(r"he='([^']*)'", raw)
        if w_match and h_match:
            try:
                info['width'] = int(w_match.group(1))
                info['height'] = int(h_match.group(1))
            except:
                pass
        
        # Extraer duración (video)
        d_match = re.search(r"d='([^']*)'", raw)
        if d_match:
            try:
                info['duration'] = int(d_match.group(1))
            except:
                pass
        
        return info
    
    def download_media(self, message: dict) -> Optional[Tuple[str, str]]:
        """
        Descarga el contenido multimedia.
        """
        info = self.extract_media_info(message)
        
        if not info['url']:
            logger.warning("No se encontró URL para descargar")
            return None
        
        url = info['url']
        file_name = info['file_name']
        
        # Crear nombre único
        from datetime import datetime
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        safe_name = f"{timestamp}_{file_name}"
        
        try:
            logger.info(f"📥 Descargando {file_name}...")
            
            size = self.client.download_file_to_folder(
                url=url,
                folder=str(self.download_folder),
                filename=safe_name
            )
            
            logger.info(f"✅ Descargado: {safe_name} ({size} bytes)")
            return str(self.download_folder / safe_name), safe_name
            
        except Exception as e:
            logger.error(f"❌ Error descargando {file_name}: {e}")
            return None