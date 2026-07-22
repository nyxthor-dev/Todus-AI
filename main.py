#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Bot de ToDus con soporte para:
- Comando start (bienvenida)
- Descarga de videos de YouTube con progreso en tiempo real
- Chat con DeepSeek AI (AIDUS)
- Manejo de mensajes multimedia entrantes
- API Flask con endpoint /health para mantener el puerto abierto en Render
"""

import os
import sys
import logging
import signal
import time
import hashlib
import threading
from pathlib import Path

# Cargar variables de entorno desde .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Añadir el directorio del SDK al path
sdk_path = Path(__file__).parent / "todus"
if sdk_path.exists() and str(sdk_path.parent) not in sys.path:
    sys.path.insert(0, str(sdk_path.parent))

# Importar Flask
from flask import Flask, jsonify

# Importar el cliente de ToDus
from todus import ToDusClient2
from todus.errors import AuthenticationError, ConnectionLostError
from todus import util

# Importar comandos y handlers
from cmd.start import handle_start
from cmd.yt import handle_yt, handle_yt_help
from cmd.ds import handle_ds, handle_ds_help
from handlers.media import MediaHandler

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Variables globales
running = True
media_handler = None
BOT_JID = None
bot_client = None

# Control de duplicados
processed_messages = set()
MAX_PROCESSED = 1000

# ============================================================
# FLASK API
# ============================================================

app = Flask(__name__)


@app.route('/health', methods=['GET'])
def health_check():
    """Endpoint de salud para Render."""
    status = {
        'status': 'healthy',
        'bot_running': running,
        'bot_connected': bot_client is not None and bot_client.logged,
        'phone': os.getenv('PHONE_NUMBER', 'not_set'),
        'timestamp': time.time()
    }
    return jsonify(status)


@app.route('/')
def index():
    """Página principal."""
    return jsonify({
        'name': 'ToDus Bot',
        'version': '1.0.0',
        'status': 'running',
        'endpoints': {
            '/health': 'Health check',
            '/': 'This page'
        }
    })


def run_flask():
    """Ejecuta el servidor Flask en un puerto específico."""
    port = int(os.getenv('PORT', 8080))
    logger.info(f"🌐 Iniciando Flask API en el puerto {port}")
    try:
        app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
    except Exception as e:
        logger.error(f"❌ Error en Flask: {e}")

# ============================================================
# FUNCIONES DEL BOT
# ============================================================

def signal_handler(sig, frame):
    """Maneja la señal de interrupción (Ctrl+C)."""
    global running
    logger.info("Recibida señal de detención. Cerrando...")
    running = False


def is_own_message(message: dict) -> bool:
    """Determina si un mensaje fue enviado por el propio bot."""
    global BOT_JID
    
    if not BOT_JID:
        return False
    
    sender = message.get('from', '')
    if not sender:
        return False
    
    sender_jid = sender.split('/')[0]
    return sender_jid == BOT_JID


def get_message_unique_id(message: dict) -> str:
    """Genera un ID único para un mensaje."""
    msg_id = message.get('id', '')
    if msg_id:
        return f"id_{msg_id}"
    
    sender = message.get('from', '')
    body = message.get('body', '')
    url = message.get('url', '')
    file_id = message.get('file_id', '')
    video_id = message.get('video_id', '')
    
    if url:
        return hashlib.md5(f"{sender}:url:{url}".encode()).hexdigest()
    if file_id:
        return hashlib.md5(f"{sender}:file:{file_id}".encode()).hexdigest()
    if video_id:
        return hashlib.md5(f"{sender}:video:{video_id}".encode()).hexdigest()
    if body:
        return hashlib.md5(f"{sender}:body:{body}".encode()).hexdigest()
    
    timestamp = message.get('sent_at', time.time())
    return hashlib.md5(f"{sender}:{timestamp}".encode()).hexdigest()


def is_duplicate(message: dict) -> bool:
    """Detecta si un mensaje ya fue procesado."""
    global processed_messages
    
    unique_id = get_message_unique_id(message)
    
    if unique_id in processed_messages:
        logger.debug(f"⚠️ Mensaje duplicado ignorado: {unique_id[:20]}...")
        return True
    
    processed_messages.add(unique_id)
    logger.debug(f"✅ Mensaje registrado: {unique_id[:20]}...")
    
    if len(processed_messages) > MAX_PROCESSED:
        to_remove = list(processed_messages)[:MAX_PROCESSED // 2]
        for old_id in to_remove:
            processed_messages.discard(old_id)
        logger.debug(f"🧹 Limpiados {len(to_remove)} mensajes antiguos del caché")
    
    return False


def handle_media_message(client: ToDusClient2, message: dict):
    """Maneja mensajes multimedia entrantes."""
    global media_handler
    
    if not media_handler:
        return
    
    sender = message.get('from', '')
    if not sender:
        return
    
    sender_phone = sender.split('@')[0]
    raw = message.get('raw', '')
    body = message.get('body', '')
    
    import re
    
    media_type = "desconocido"
    file_name = "archivo"
    file_size = 0
    
    if '<image' in raw:
        media_type = "📷 Imagen"
        name_match = re.search(r"n='([^']*)'", raw)
        if name_match:
            file_name = name_match.group(1)
        size_match = re.search(r"s='([^']*)'", raw)
        if size_match:
            try:
                file_size = int(size_match.group(1))
            except:
                pass
    elif '<video' in raw:
        media_type = "🎬 Vídeo"
        name_match = re.search(r"n='([^']*)'", raw)
        if name_match:
            file_name = name_match.group(1)
        size_match = re.search(r"s='([^']*)'", raw)
        if size_match:
            try:
                file_size = int(size_match.group(1))
            except:
                pass
    elif '<sticker' in raw:
        media_type = "🏷️ Sticker"
        name_match = re.search(r"n='([^']*)'", raw)
        if name_match:
            file_name = name_match.group(1)
    elif '<contact' in raw:
        media_type = "👤 Contacto"
        name_match = re.search(r"n='([^']*)'", raw)
        if name_match:
            file_name = name_match.group(1)
    elif '<file' in raw:
        media_type = "📎 Archivo"
        name_match = re.search(r"n='([^']*)'", raw)
        if name_match:
            file_name = name_match.group(1)
        size_match = re.search(r"s='([^']*)'", raw)
        if size_match:
            try:
                file_size = int(size_match.group(1))
            except:
                pass
    
    response = f"📥 **Recibido: {media_type}**\n\n"
    response += f"📄 Nombre: {file_name}\n"
    
    if file_size > 0:
        response += f"📦 Tamaño: {util.format_size(file_size)}\n"
    
    if body:
        response += f"📝 Texto: {body}\n"
    
    response += f"\n✅ Archivo recibido correctamente!"
    
    try:
        client.send_message(sender_phone, response)
        logger.info(f"✅ Confirmación de multimedia enviada a {sender_phone}")
    except Exception as e:
        logger.error(f"❌ Error respondiendo a multimedia: {e}")


def process_message(client: ToDusClient2, message: dict):
    """Procesa un mensaje entrante."""
    # 1. Ignorar mensajes del propio bot
    if is_own_message(message):
        logger.debug(f"Ignorando mensaje propio")
        return
    
    # 2. Verificar duplicado
    if is_duplicate(message):
        logger.debug(f"Mensaje duplicado ignorado")
        return
    
    # 3. Verificar multimedia
    raw = message.get('raw', '')
    is_media = any([
        '<file' in raw,
        '<image' in raw, 
        '<video' in raw,
        '<sticker' in raw,
        '<contact' in raw,
        '<location' in raw,
        '<event' in raw,
        message.get('url'),
        message.get('file_id'),
        message.get('video_url'),
        message.get('sticker_id'),
    ])
    
    if is_media:
        logger.info(f"📷 Mensaje multimedia detectado")
        handle_media_message(client, message)
        return
    
    # 4. Procesar mensajes de texto
    body = message.get('body', '').strip()
    if not body:
        return
    
    if message.get('is_group'):
        return
    
    sender = message.get('from', '')
    if not sender:
        return
    
    sender_phone = sender.split('@')[0]
    logger.info(f"Mensaje de {sender_phone}: {body}")
    
    command = body.lower().strip()
    if command.startswith('!'):
        command = command[1:]
    
    try:
        if command == 'start':
            handle_start(client, message)
        elif command == 'yt' or command.startswith('yt '):
            handle_yt(client, message)
        elif command == 'ythelp':
            handle_yt_help(client, message)
        elif command == 'ds' or command.startswith('ds '):
            handle_ds(client, message)
        elif command == 'dshelp':
            handle_ds_help(client, message)
        else:
            pass
            
    except Exception as e:
        logger.error(f"Error procesando comando {command}: {e}")
        try:
            client.send_message(
                sender_phone,
                f"❌ Error al procesar el comando: {str(e)[:100]}"
            )
        except:
            pass


def run_bot():
    """Ejecuta el bot de ToDus."""
    global running, media_handler, BOT_JID, bot_client
    
    phone = os.getenv('PHONE_NUMBER')
    password = os.getenv('PASSWORD')
    
    if not phone or not password:
        logger.error("❌ Error: PHONE_NUMBER y PASSWORD deben estar configurados en .env")
        return
    
    logger.info(f"🚀 Iniciando bot para {phone}")
    
    client = ToDusClient2(
        phone_number=phone,
        password=password,
        verify_ssl=False,
    )
    
    bot_client = client
    BOT_JID = util.build_jid(phone)
    logger.info(f"🤖 JID del bot: {BOT_JID}")
    
    media_handler = MediaHandler(client, download_folder="downloads")
    
    client.events.on('message')(lambda event: process_message(client, event))
    
    try:
        logger.info("🔐 Iniciando sesión...")
        client.login()
        logger.info("✅ Sesión iniciada correctamente!")
        logger.info(f"📱 Teléfono: {phone}")
        logger.info("👂 Escuchando mensajes...")
        logger.info("")
        logger.info("📌 Comandos disponibles:")
        logger.info("  • start - Mensaje de bienvenida")
        logger.info("  • yt <url> [formato] - Descarga videos de YouTube")
        logger.info("  • ds <mensaje> - Chat con AIDUS (DeepSeek AI)")
        logger.info("  • ds /help - Ayuda de AIDUS")
        logger.info("")
        logger.info("📷 También puedo recibir imágenes, vídeos y archivos")
        logger.info("")
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        client.listen_messages(client.token, lambda msg: None)
        
    except AuthenticationError as e:
        logger.error(f"❌ Error de autenticación: {e}")
    except ConnectionLostError as e:
        logger.error(f"❌ Conexión perdida: {e}")
    except KeyboardInterrupt:
        logger.info("👋 Bot detenido por el usuario.")
    except Exception as e:
        logger.exception(f"❌ Error inesperado: {e}")
    finally:
        logger.info("👋 Bot detenido.")


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    # Iniciar el bot en un hilo separado
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Esperar un momento para que el bot inicie
    time.sleep(2)
    
    # Iniciar Flask (bloquea el hilo principal, mantiene el puerto abierto)
    run_flask()