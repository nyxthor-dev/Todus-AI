#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Bot de ToDus con soporte para:
- Comando start (bienvenida)
- Descarga de videos de YouTube con progreso en tiempo real
- Chat con DeepSeek AI (AIDUS)
- Manejo de mensajes multimedia entrantes
- API Flask con endpoint /health para mantener el puerto abierto en Render
- Anti-spam mejorado con detección de mensajes offline
"""

import os
import sys
import logging
import signal
import time
import hashlib
import threading
from collections import deque
from datetime import datetime, timedelta
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

# ============================================================
# VARIABLES GLOBALES
# ============================================================

running = True
media_handler = None
BOT_JID = None
bot_client = None

# ============================================================
# ANTI-SPAM MEJORADO
# ============================================================

class AntiSpamManager:
    """
    Sistema anti-spam mejorado con:
    - Cache de IDs de mensajes (detecta offline duplicates)
    - Limitador de frecuencia por usuario
    - Limpieza automática
    """
    
    def __init__(self, max_messages: int = 1000, cooldown_seconds: int = 3):
        """
        Args:
            max_messages: Máximo de mensajes en caché
            cooldown_seconds: Segundos entre mensajes del mismo usuario
        """
        self.max_messages = max_messages
        self.cooldown_seconds = cooldown_seconds
        
        # Cache de IDs de mensajes procesados
        self.processed_ids = set()
        # Cache temporal para mensajes recientes (para detección de offline spam)
        self.recent_ids = deque(maxlen=200)
        
        # Control de frecuencia por usuario
        self.user_last_message = {}  # {user_id: timestamp}
        self.user_message_count = {}  # {user_id: count}
        
        # Estadísticas
        self.stats = {
            'total_processed': 0,
            'duplicates_blocked': 0,
            'rate_limited_blocked': 0,
            'offline_spam_blocked': 0,
            'last_cleanup': time.time()
        }
        
        logger.info("🛡️ Anti-Spam Manager inicializado")
    
    def _cleanup(self):
        """Limpia cachés antiguos para evitar memory leak."""
        now = time.time()
        
        # Limpiar cada 5 minutos
        if now - self.stats['last_cleanup'] > 300:
            # Limpiar processed_ids si excede el límite
            if len(self.processed_ids) > self.max_messages:
                # Convertir a lista, eliminar la mitad más antigua
                old_ids = list(self.processed_ids)[:self.max_messages // 2]
                for old_id in old_ids:
                    self.processed_ids.discard(old_id)
                logger.debug(f"🧹 Limpiados {len(old_ids)} mensajes antiguos de processed_ids")
            
            # Limpiar user_last_message (eliminar usuarios inactivos > 1 hora)
            inactive_users = [
                user for user, ts in self.user_last_message.items()
                if now - ts > 3600
            ]
            for user in inactive_users:
                self.user_last_message.pop(user, None)
                self.user_message_count.pop(user, None)
            
            if inactive_users:
                logger.debug(f"🧹 Limpiados {len(inactive_users)} usuarios inactivos")
            
            self.stats['last_cleanup'] = now
    
    def is_duplicate_id(self, msg_id: str) -> bool:
        """
        Verifica si un ID de mensaje ya fue procesado.
        Útil para detectar mensajes offline que ToDus reenvía.
        """
        if not msg_id:
            return False
        
        # Verificar en caché principal
        if msg_id in self.processed_ids:
            self.stats['offline_spam_blocked'] += 1
            logger.debug(f"🔄 Mensaje offline detectado (ID: {msg_id[:20]}...)")
            return True
        
        # Verificar en caché reciente (para mensajes duplicados rápidos)
        if msg_id in self.recent_ids:
            self.stats['duplicates_blocked'] += 1
            logger.debug(f"⚠️ Mensaje duplicado reciente (ID: {msg_id[:20]}...)")
            return True
        
        return False
    
    def register_message(self, msg_id: str, user_id: str):
        """
        Registra un mensaje como procesado.
        """
        if msg_id:
            # Agregar a cachés
            self.processed_ids.add(msg_id)
            self.recent_ids.append(msg_id)
            
            # Limpiar si es necesario
            self._cleanup()
        
        # Actualizar estadísticas del usuario
        if user_id:
            self.user_last_message[user_id] = time.time()
            self.user_message_count[user_id] = self.user_message_count.get(user_id, 0) + 1
        
        self.stats['total_processed'] += 1
    
    def is_rate_limited(self, user_id: str) -> bool:
        """
        Verifica si un usuario está enviando demasiados mensajes.
        """
        if not user_id:
            return False
        
        now = time.time()
        last_time = self.user_last_message.get(user_id, 0)
        
        # Si el usuario no ha enviado mensajes antes, no está limitado
        if last_time == 0:
            return False
        
        # Verificar cooldown
        if now - last_time < self.cooldown_seconds:
            self.stats['rate_limited_blocked'] += 1
            logger.debug(f"⏱️ Rate limit para {user_id}: {now - last_time:.2f}s desde último mensaje")
            return True
        
        return False
    
    def get_stats(self) -> dict:
        """Obtiene estadísticas del anti-spam."""
        return {
            **self.stats,
            'cache_size': len(self.processed_ids),
            'recent_size': len(self.recent_ids),
            'active_users': len(self.user_last_message),
            'cooldown_seconds': self.cooldown_seconds,
            'max_messages': self.max_messages
        }
    
    def reset(self):
        """Reinicia todas las cachés."""
        self.processed_ids.clear()
        self.recent_ids.clear()
        self.user_last_message.clear()
        self.user_message_count.clear()
        self.stats = {
            'total_processed': 0,
            'duplicates_blocked': 0,
            'rate_limited_blocked': 0,
            'offline_spam_blocked': 0,
            'last_cleanup': time.time()
        }
        logger.info("🔄 Anti-Spam Manager reiniciado")


# Instancia global del anti-spam
anti_spam = AntiSpamManager(max_messages=2000, cooldown_seconds=2)


# ============================================================
# FLASK API
# ============================================================

app = Flask(__name__)


@app.route('/health', methods=['GET'])
@app.route('/api/health', methods=['GET'])  # 🔥 Alias para compatibilidad
def health_check():
    """Endpoint de salud para Render."""
    status = {
        'status': 'healthy',
        'bot_running': running,
        'bot_connected': bot_client is not None and bot_client.logged,
        'phone': os.getenv('PHONE_NUMBER', 'not_set'),
        'timestamp': time.time(),
        'anti_spam': anti_spam.get_stats()
    }
    return jsonify(status)


@app.route('/anti-spam/stats', methods=['GET'])
def anti_spam_stats():
    """Endpoint para ver estadísticas del anti-spam."""
    return jsonify(anti_spam.get_stats())


@app.route('/anti-spam/reset', methods=['POST'])
def anti_spam_reset():
    """Endpoint para reiniciar el anti-spam."""
    anti_spam.reset()
    return jsonify({'status': 'reset', 'message': 'Anti-Spam reiniciado'})


@app.route('/')
def index():
    """Página principal."""
    return jsonify({
        'name': 'ToDus Bot',
        'version': '1.0.0',
        'status': 'running',
        'endpoints': {
            '/health': 'Health check',
            '/api/health': 'Health check (alias)',
            '/anti-spam/stats': 'Anti-spam statistics',
            '/anti-spam/reset': 'Reset anti-spam (POST)',
            '/': 'This page'
        }
    })


def run_flask():
    """Ejecuta el servidor Flask."""
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
    """
    Genera un ID único para un mensaje.
    PRIORIZA el ID del mensaje si existe (para detectar offline spam).
    """
    # 1. ID del mensaje (más fiable para offline spam)
    msg_id = message.get('id', '')
    if msg_id:
        return f"id_{msg_id}"
    
    # 2. Si no tiene ID, usar combinación de atributos
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
    
    # 3. Último recurso: timestamp
    timestamp = message.get('sent_at', time.time())
    return hashlib.md5(f"{sender}:{timestamp}".encode()).hexdigest()


def extract_user_id(message: dict) -> str:
    """Extrae el ID del usuario del mensaje."""
    sender = message.get('from', '')
    if not sender:
        return ''
    return sender.split('/')[0]


def process_message(client: ToDusClient2, message: dict):
    """
    Procesa un mensaje entrante con anti-spam mejorado.
    """
    global processed_messages
    
    # 1. Ignorar mensajes del propio bot
    if is_own_message(message):
        logger.debug("Ignorando mensaje propio")
        return
    
    # 2. Extraer información del mensaje
    msg_id = message.get('id', '')
    unique_id = get_message_unique_id(message)
    user_id = extract_user_id(message)
    
    # 3. Verificar si es un mensaje offline duplicado (mismo ID)
    if anti_spam.is_duplicate_id(msg_id):
        logger.warning(f"🔄 Mensaje offline/duplicado ignorado (ID: {msg_id[:20] if msg_id else 'sin_id'})")
        return
    
    # 4. Verificar rate limit por usuario
    if anti_spam.is_rate_limited(user_id):
        logger.warning(f"⏱️ Rate limit excedido para {user_id}")
        return
    
    # 5. Registrar mensaje como procesado
    anti_spam.register_message(msg_id, user_id)
    
    # 6. Verificar si es multimedia
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
    
    if message.get('is_group'):
        return
    
    if not user_id:
        return
    
    sender_phone = user_id.split('@')[0]
    logger.info(f"Mensaje de {sender_phone}: {body[:50]}...")
    
    # 8. Normalizar comando
    command = body.lower().strip()
    if command.startswith('!'):
        command = command[1:]
    
    # 9. Procesar comandos
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
            # Comando no reconocido: ignorar
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
        logger.info(f"🛡️ Anti-Spam: Cooldown={anti_spam.cooldown_seconds}s, MaxCache={anti_spam.max_messages}")
        logger.info("")
        
        # ⚠️ NO llamamos a signal.signal aquí porque estamos en un hilo secundario
        
        # Bucle principal - escuchar mensajes
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
# MAIN - Hilo principal
# ============================================================

if __name__ == "__main__":
    # Registrar manejadores de señales en el hilo principal
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Iniciar el bot en un hilo separado
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Esperar un momento para que el bot inicie
    time.sleep(2)
    
    # Iniciar Flask (bloquea el hilo principal, mantiene el puerto abierto)
    run_flask()