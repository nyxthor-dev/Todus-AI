#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Bot de ToDus con soporte para:
- Comando start (bienvenida)
- Descarga de videos de YouTube con progreso en tiempo real
- Manejo de mensajes multimedia entrantes
- Servidor Flask con endpoint /api/health (optimizado para Render)
"""

import os
import sys
import logging
import signal
import time
import hashlib
import threading
import atexit
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

# Importar el cliente de ToDus
from todus import ToDusClient2
from todus.errors import AuthenticationError, ConnectionLostError
from todus import util

#comandos
from cmd import handle_start
from cmd.yt import handle_yt, handle_yt_help
from cmd.ds import handle_ds, handle_ds_help
from handlers.media import MediaHandler

# Importar Flask
from flask import Flask, jsonify, request
import requests

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
bot_start_time = time.time()
client_instance = None
flask_thread = None

# Control de duplicados
processed_messages = set()
MAX_PROCESSED = 500

# Servidor Flask
flask_app = Flask(__name__)
bot_status = {
    'status': 'initializing',
    'start_time': bot_start_time,
    'uptime': 0,
    'phone': '',
    'messages_processed': 0,
    'is_running': True,
    'authenticated': False,
    'version': '1.0.0'
}


@flask_app.route('/api/health', methods=['GET', 'HEAD'])
def health_check():
    """
    Endpoint de salud para verificar el estado del bot.
    """
    global bot_status, running, client_instance
    
    # Actualizar estado
    bot_status['uptime'] = int(time.time() - bot_start_time)
    bot_status['is_running'] = running
    
    # Verificar conexión del cliente
    if client_instance:
        try:
            # Verificar si el cliente tiene token
            if hasattr(client_instance, 'token') and client_instance.token:
                bot_status['status'] = 'healthy'
                bot_status['authenticated'] = True
            else:
                bot_status['status'] = 'degraded'
                bot_status['authenticated'] = False
        except Exception as e:
            bot_status['status'] = 'degraded'
            bot_status['authenticated'] = False
    else:
        bot_status['status'] = 'unhealthy'
        bot_status['authenticated'] = False
    
    # Verificar que el bot está corriendo
    if not running:
        bot_status['status'] = 'shutdown'
    
    # Devolver respuesta en formato JSON
    response_data = {
        'status': bot_status['status'],
        'timestamp': time.time(),
        'uptime_seconds': bot_status['uptime'],
        'uptime_human': f"{bot_status['uptime'] // 3600}h {((bot_status['uptime'] % 3600) // 60)}m {bot_status['uptime'] % 60}s",
        'phone': bot_status['phone'],
        'messages_processed': bot_status['messages_processed'],
        'authenticated': bot_status.get('authenticated', False),
        'is_running': bot_status['is_running'],
        'version': bot_status['version']
    }
    
    # Para HEAD requests (usado por monitores como Uptime Kuma)
    if request.method == 'HEAD':
        status_code = 200 if bot_status['status'] == 'healthy' else 503
        return '', status_code
    
    status_code = 200 if bot_status['status'] == 'healthy' else 503
    return jsonify(response_data), status_code


@flask_app.route('/api/health/live', methods=['GET'])
def liveness_check():
    """
    Endpoint de liveness para Render.
    """
    return jsonify({'status': 'alive'}), 200


@flask_app.route('/api/health/ready', methods=['GET'])
def readiness_check():
    """
    Endpoint de readiness para Render.
    """
    if bot_status['status'] == 'healthy':
        return jsonify({'status': 'ready'}), 200
    return jsonify({'status': 'not_ready'}), 503


@flask_app.route('/', methods=['GET'])
def root():
    """
    Endpoint raíz para verificar que el servidor está funcionando.
    """
    return jsonify({
        'service': 'ToDus Bot',
        'status': bot_status['status'],
        'version': bot_status['version'],
        'endpoints': {
            '/': 'Información del servicio',
            '/api/health': 'Health check completo',
            '/api/health/live': 'Liveness probe',
            '/api/health/ready': 'Readiness probe'
        }
    }), 200


def start_flask_server():
    """
    Inicia el servidor Flask en el puerto asignado por Render.
    """
    # Render asigna el puerto a través de la variable de entorno PORT
    port = int(os.getenv('PORT', 5000))
    host = os.getenv('HOST', '0.0.0.0')
    
    logger.info(f"🌐 Iniciando servidor Flask en {host}:{port}")
    logger.info(f"🌐 Endpoint de salud: http://{host}:{port}/api/health")
    
    # Configurar el servidor para Render
    flask_app.run(host=host, port=port, debug=False, use_reloader=False)


def signal_handler(sig, frame):
    """Maneja la señal de interrupción (Ctrl+C)."""
    global running
    logger.info("Recibida señal de detención. Cerrando...")
    running = False


def cleanup():
    """Limpieza al finalizar el programa."""
    global running
    running = False
    logger.info("🧹 Limpieza finalizada")


def is_own_message(message: dict) -> bool:
    """Determina si un mensaje fue enviado por el propio bot."""
    global BOT_JID
    
    if not BOT_JID:
        return False
    
    sender = message.get('from', '')
    if not sender:
        return False
    
    # Extraer JID sin recurso
    sender_jid = sender.split('/')[0]
    
    # Si el remitente es el bot -> mensaje enviado por el bot
    return sender_jid == BOT_JID


def get_message_unique_id(message: dict) -> str:
    """
    Genera un ID único para un mensaje.
    """
    msg_id = message.get('id', '')
    if msg_id:
        return msg_id
    
    # Si no tiene ID, usar combinación de atributos
    sender = message.get('from', '')
    body = message.get('body', '')
    url = message.get('url', '')
    file_id = message.get('file_id', '')
    video_id = message.get('video_id', '')
    raw = message.get('raw', '')[:100]
    
    # Crear hash único basado en contenido
    unique_str = f"{sender}:{body}:{url}:{file_id}:{video_id}:{raw}"
    return hashlib.md5(unique_str.encode()).hexdigest()


def handle_media_message(client: ToDusClient2, message: dict):
    """
    Maneja mensajes multimedia entrantes.
    """
    global media_handler
    
    if not media_handler:
        return
    
    sender = message.get('from', '')
    if not sender:
        return
    
    sender_phone = sender.split('@')[0]
    
    # Extraer información del mensaje usando el raw XML
    raw = message.get('raw', '')
    body = message.get('body', '')
    
    # Detectar tipo de multimedia por el raw
    media_type = "desconocido"
    file_name = "archivo"
    file_size = 0
    
    import re
    
    # Buscar en el raw
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
    
    # Construir respuesta
    response = f"📥 **Recibido: {media_type}**\n\n"
    response += f"📄 Nombre: {file_name}\n"
    
    if file_size > 0:
        response += f"📦 Tamaño: {util.format_size(file_size)}\n"
    
    if body:
        response += f"📝 Texto: {body}\n"
    
    response += f"\n✅ Archivo recibido correctamente!"
    
    try:
        msg_id = client.send_message(sender_phone, response)
        logger.info(f"✅ Confirmación de multimedia enviada a {sender_phone} (msg_id: {msg_id})")
        
    except Exception as e:
        logger.error(f"❌ Error respondiendo a multimedia: {e}")


def process_message(client: ToDusClient2, message: dict):
    """
    Procesa un mensaje entrante.
    """
    global processed_messages, bot_status
    
    # 1. Obtener ID único del mensaje
    msg_id = get_message_unique_id(message)
    
    # 2. Verificar si ya procesamos este mensaje
    if msg_id in processed_messages:
        logger.debug(f"Mensaje duplicado ignorado: {msg_id}")
        return
    
    # 3. Marcar como procesado
    processed_messages.add(msg_id)
    bot_status['messages_processed'] += 1
    
    # 4. Limitar memoria
    if len(processed_messages) > MAX_PROCESSED:
        to_remove = list(processed_messages)[:MAX_PROCESSED // 2]
        for old_id in to_remove:
            processed_messages.discard(old_id)
        logger.debug(f"Limpiados {len(to_remove)} mensajes antiguos del caché")
    
    # 5. Ignorar mensajes del propio bot
    if is_own_message(message):
        logger.debug(f"Ignorando mensaje propio")
        return
    
    # 6. Verificar si es un mensaje multimedia
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
    
    # 7. Procesar mensajes de texto
    body = message.get('body', '').strip()
    if not body:
        return
    
    # 8. Ignorar mensajes de grupos
    if message.get('is_group'):
        return
    
    # 9. Extraer remitente
    sender = message.get('from', '')
    if not sender:
        return
    
    sender_phone = sender.split('@')[0]
    logger.info(f"Mensaje de {sender_phone}: {body}")
    
    # 10. Normalizar comando
    command = body.lower().strip()
    if command.startswith('!'):
        command = command[1:]
    
    # 11. Procesar comandos
    try:
        if command == 'start':
            handle_start(client, message)
        elif command == 'ds' or command.startswith('ds '):
            handle_ds(client, message)
        elif command == 'dshelp':
            handle_ds_help(client, message)
        else:

            # Comando no reconocido: ignorar silenciosamente
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


def main():
    """Función principal del bot."""
    global running, media_handler, BOT_JID, client_instance, bot_status, flask_thread
    
    # Registrar función de limpieza
    atexit.register(cleanup)
    
    # Obtener credenciales
    phone = os.getenv('PHONE_NUMBER')
    password = os.getenv('PASSWORD')
    
    if not phone or not password:
        logger.error("❌ Error: PHONE_NUMBER y PASSWORD deben estar configurados en .env")
        logger.error("📝 Crea un archivo .env con:")
        logger.error("PHONE_NUMBER=5300000000")
        logger.error("PASSWORD=tu_contraseña")
        sys.exit(1)
    
    logger.info(f"🚀 Iniciando bot para {phone}")
    
    # Actualizar estado del bot
    bot_status['phone'] = phone
    bot_status['status'] = 'starting'
    
    # Crear el cliente
    client = ToDusClient2(
        phone_number=phone,
        password=password,
        verify_ssl=False,
    )
    client_instance = client
    
    # Guardar JID del bot para comparar
    BOT_JID = util.build_jid(phone)
    logger.info(f"🤖 JID del bot: {BOT_JID}")
    
    # Inicializar el manejador de medios
    media_handler = MediaHandler(client, download_folder="downloads")
    
    # Registrar el manejador de mensajes en el EventBus
    client.events.on('message')(lambda event: process_message(client, event))
    
    # Iniciar el servidor Flask en un hilo separado
    # Render usará el puerto de la variable PORT
    flask_thread = threading.Thread(
        target=start_flask_server,
        daemon=True
    )
    flask_thread.start()
    
    # Esperar un momento para que el servidor Flask se inicie
    time.sleep(2)
    
    try:
        # Iniciar sesión
        logger.info("🔐 Iniciando sesión...")
        client.login()
        logger.info("✅ Sesión iniciada correctamente!")
        bot_status['status'] = 'healthy'
        bot_status['authenticated'] = True
        
        logger.info(f"📱 Teléfono: {phone}")
        logger.info("👂 Escuchando mensajes... (presiona Ctrl+C para detener)")
        logger.info("")
        logger.info("📌 Comandos disponibles:")
        logger.info("  • start - Mensaje de bienvenida")
        logger.info("  • yt <url> [formato] - Descarga y envía un video de YouTube")
        logger.info("  • ythelp - Ayuda del comando yt")
        logger.info("")
        logger.info("📷 También puedo recibir imágenes, vídeos y archivos")
        logger.info("   Envíame un archivo y lo procesaré")
        logger.info("")
        
        # Manejar señales
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Iniciar escucha (bloqueante)
        client.listen_messages(client.token, lambda msg: None)
        
    except AuthenticationError as e:
        logger.error(f"❌ Error de autenticación: {e}")
        logger.error("   Verifica que el número y la contraseña sean correctos.")
        bot_status['status'] = 'unhealthy'
        sys.exit(1)
    except ConnectionLostError as e:
        logger.error(f"❌ Conexión perdida: {e}")
        bot_status['status'] = 'unhealthy'
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("👋 Bot detenido por el usuario.")
        bot_status['status'] = 'shutdown'
        sys.exit(0)
    except Exception as e:
        logger.exception(f"❌ Error inesperado: {e}")
        bot_status['status'] = 'unhealthy'
        sys.exit(1)
    finally:
        running = False
        bot_status['is_running'] = False
        bot_status['status'] = 'shutdown'
        logger.info("👋 Bot detenido.")


if __name__ == "__main__":
    main()