#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Comando para interactuar con DeepSeek AI en ToDus.
Flujo optimizado:
1. Mensaje inicial: "🤔 Pensando..."
2. Se muestra el pensamiento (think) cuando llega
3. La respuesta (response) se edita con CADA fragmento que llega
4. Al recibir 'done', se muestra el mensaje final completo
"""

import re
import logging
import time
import json
import requests
from typing import Dict, Optional, Tuple, List, Generator
from datetime import datetime

logger = logging.getLogger(__name__)

# ============================================================
# CONFIGURACIÓN DE LA API
# ============================================================

API_URL = "https://ds-flaskapi.onrender.com"
TIMEOUT = 120
VERSION = "1.0.0"

# ============================================================
# CLIENTE DEEPSEEK INTEGRADO
# ============================================================

class DeepSeekClient:
    """Cliente para interactuar con la API de DeepSeek."""
    
    def __init__(self, api_url: str = API_URL, timeout: int = TIMEOUT):
        self.api_url = api_url.rstrip('/')
        self.timeout = timeout
        self.session_id = None
        self.parent_id = None
        self.thinking_enabled = True
        self.search_enabled = True
        self.conversation_history = []
        self.session_created_at = None
        
        logger.info(f"Cliente DeepSeek inicializado con API: {self.api_url}")
    
    def create_session(self) -> str:
        """Crea una nueva sesión de chat."""
        try:
            logger.debug("Creando nueva sesión...")
            resp = requests.post(
                f"{self.api_url}/api/session",
                timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()
            
            self.session_id = data.get('session_id')
            if not self.session_id:
                raise Exception(f"No se recibió session_id: {data}")
            
            self.session_created_at = datetime.now()
            self.conversation_history = []
            logger.info(f"Sesión creada: {self.session_id}")
            return self.session_id
            
        except requests.RequestException as e:
            logger.error(f"Error de red al crear sesión: {e}")
            raise Exception(f"Error al crear sesión: {e}")
        except Exception as e:
            logger.error(f"Error al crear sesión: {e}")
            raise
    
    def reset_session(self) -> str:
        """Reinicia la sesión actual."""
        logger.info("Reiniciando sesión...")
        self.session_id = None
        self.parent_id = None
        self.conversation_history = []
        return self.create_session()
    
    def set_thinking(self, enabled: bool):
        """Activa o desactiva el pensamiento profundo."""
        self.thinking_enabled = enabled
        logger.debug(f"DeepThink {'activado' if enabled else 'desactivado'}")
    
    def set_search(self, enabled: bool):
        """Activa o desactiva la búsqueda inteligente."""
        self.search_enabled = enabled
        logger.debug(f"Búsqueda {'activada' if enabled else 'desactivada'}")
    
    def send_message(
        self,
        prompt: str,
        file_ids: Optional[List[str]] = None,
        parent_id: Optional[int] = None,
        stream: bool = True
    ) -> Generator[Tuple[str, str, Optional[int]], None, None]:
        """
        Envía un mensaje y devuelve un generador de eventos.
        
        Yields:
            (tipo, contenido, message_id)
            - 'think': fragmento de pensamiento
            - 'response': fragmento de respuesta
            - 'done': mensaje completado
            - 'error': error
        """
        if not self.session_id:
            raise Exception("Primero debes crear una sesión con create_session()")
        
        payload = {
            "session_id": self.session_id,
            "prompt": prompt,
            "thinking_enabled": self.thinking_enabled,
            "search_enabled": self.search_enabled
        }
        if parent_id:
            payload["parent_message_id"] = parent_id
        if file_ids:
            payload["ref_file_ids"] = file_ids
        
        logger.debug(f"Enviando mensaje: {prompt[:50]}...")
        
        try:
            with requests.post(
                f"{self.api_url}/api/chat",
                json=payload,
                stream=stream,
                timeout=self.timeout
            ) as r:
                
                if r.status_code != 200:
                    error_msg = f"HTTP {r.status_code}: {r.text[:200]}"
                    logger.error(error_msg)
                    yield ('error', error_msg, None)
                    return
                
                event_type = None
                think_full = []
                response_full = []
                done_id = None
                
                for line in r.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    
                    if line.startswith('event: '):
                        event_type = line[7:].strip()
                        continue
                    
                    if line.startswith('data: '):
                        data_str = line[6:].strip()
                        
                        if not data_str or data_str == '""' or data_str == '"':
                            continue
                        
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            data = data_str
                        
                        if event_type == 'think':
                            think_text = str(data)
                            # Eliminar "FINISHED"
                            think_text = re.sub(r'\s*FINISHED\s*', '', think_text, flags=re.IGNORECASE)
                            think_full.append(think_text)
                            yield ('think', think_text, None)
                        
                        elif event_type == 'response':
                            response_text = str(data)
                            # Eliminar "FINISHED"
                            response_text = re.sub(r'\s*FINISHED\s*', '', response_text, flags=re.IGNORECASE)
                            response_full.append(response_text)
                            yield ('response', response_text, None)
                        
                        elif event_type == 'done':
                            done_id = data
                            yield ('done', None, done_id)
                            break
                        
                        elif event_type == 'error':
                            logger.error(f"Error del servidor: {data}")
                            yield ('error', str(data), None)
                            return
                
                # Si no se recibió 'done', pero hay datos, enviar como done
                if not done_id and (think_full or response_full):
                    yield ('done', None, None)
                    
        except requests.Timeout:
            logger.error("Timeout en la petición")
            yield ('error', 'Timeout: La respuesta tardó demasiado', None)
        except requests.RequestException as e:
            logger.error(f"Error de red: {e}")
            yield ('error', f'Error de red: {str(e)}', None)
        except Exception as e:
            logger.error(f"Error inesperado: {e}")
            yield ('error', f'Error inesperado: {str(e)}', None)
    
    def get_status(self) -> Dict:
        """Devuelve el estado actual del cliente."""
        return {
            "api_url": self.api_url,
            "session_id": self.session_id,
            "parent_id": self.parent_id,
            "thinking_enabled": self.thinking_enabled,
            "search_enabled": self.search_enabled,
            "session_created_at": self.session_created_at.isoformat() if self.session_created_at else None,
            "message_count": len(self.conversation_history),
            "version": VERSION
        }

# ============================================================
# PROMPT DEL SISTEMA
# ============================================================

SYSTEM_PROMPT = """Eres AIDUS, una asistente de inteligencia artificial creada para ayudar en ToDus.

REGLAS OBLIGATORIAS:
1. NUNCA generes código en ningún lenguaje de programación (Python, JavaScript, etc.)
2. NUNCA generes pseudocódigo ni algoritmos en formato código
3. Tus respuestas deben ser PREFERIBLEMENTE CORTAS y EFICIENTES
4. NUNCA des datos falsos o inventados
5. Si algo es ambiguo o no lo sabes, PREGUNTA a qué se refiere el usuario
6. No uses listas numeradas extensas, prefiere texto fluido
7. Usa formato Markdown básico: **negrita**, *cursiva*, > citas, --- separadores
8. Sé amable y directa en tus respuestas

CARACTERÍSTICAS SIEMPRE ACTIVAS:
- Búsqueda web para información actualizada
- Pensamiento profundo para análisis complejos

RESPONDE SIEMPRE EN ESPAÑOL."""

# ============================================================
# GESTOR DE SESIONES
# ============================================================

class SessionManager:
    """Gestiona sesiones de DeepSeek por usuario."""
    
    def __init__(self):
        self.sessions: Dict[str, Dict] = {}
        self.clients: Dict[str, DeepSeekClient] = {}
    
    def get_or_create_session(self, user_id: str) -> Dict:
        """Obtiene la sesión de un usuario, crea una nueva si no existe."""
        if user_id not in self.sessions:
            return self.create_session(user_id)
        return self.sessions[user_id]
    
    def create_session(self, user_id: str) -> Dict:
        """Crea una nueva sesión para un usuario."""
        logger.info(f"🆕 Creando sesión DeepSeek para {user_id}")
        
        client = DeepSeekClient()
        session_id = client.create_session()
        
        # DeepThink y búsqueda SIEMPRE activos
        client.set_thinking(True)
        client.set_search(True)
        
        self.clients[user_id] = client
        self.sessions[user_id] = {
            'session_id': session_id,
            'client': client,
            'created_at': datetime.now(),
            'message_count': 0,
            'last_message': None
        }
        
        return self.sessions[user_id]
    
    def reset_session(self, user_id: str) -> Dict:
        """Reinicia la sesión de un usuario."""
        if user_id in self.clients:
            client = self.clients[user_id]
            client.reset_session()
            client.set_thinking(True)
            client.set_search(True)
            self.sessions[user_id]['created_at'] = datetime.now()
            self.sessions[user_id]['message_count'] = 0
            logger.info(f"🔄 Sesión reiniciada para {user_id}")
        else:
            return self.create_session(user_id)
        
        return self.sessions[user_id]
    
    def get_client(self, user_id: str) -> Optional[DeepSeekClient]:
        """Obtiene el cliente de un usuario."""
        return self.clients.get(user_id)

# ============================================================
# PROCESAMIENTO DE TEXTO PARA TODUS
# ============================================================

def clean_markdown(text: str) -> str:
    """Limpia Markdown para ToDus."""
    if not text:
        return ""
    
    # Eliminar "FINISHED"
    text = re.sub(r'\s*FINISHED\s*', '', text, flags=re.IGNORECASE)
    
    # Eliminar bloques de código
    text = re.sub(r'```[a-zA-Z]*\n.*?```', '', text, flags=re.DOTALL)
    text = re.sub(r'`[^`]*`', '', text)
    
    # Limpiar espacios
    text = re.sub(r' +', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text.strip()


def format_for_todus(text: str) -> str:
    """Formatea texto para ToDus con Markdown básico."""
    if not text:
        return ""
    
    text = clean_markdown(text)
    
    # Convertir listas * a +
    text = re.sub(r'^\s*\*\s+', '+ ', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*-\s+', '+ ', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\d+\.\s+', '+ ', text, flags=re.MULTILINE)
    
    # Convertir # a negrita
    lines = text.split('\n')
    formatted_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            formatted_lines.append('')
        elif line.startswith('# '):
            formatted_lines.append(f'**{line[2:]}**')
        elif line.startswith('## '):
            formatted_lines.append(f'**{line[3:]}**')
        elif line.startswith('### '):
            formatted_lines.append(f'*{line[4:]}*')
        else:
            formatted_lines.append(line)
    
    return '\n'.join(formatted_lines)

# ============================================================
# ACTUALIZACIÓN DE MENSAJES
# ============================================================

def build_message(response_text: str, think_text: str = "", 
                  has_think: bool = False, is_done: bool = False) -> str:
    """
    Construye el mensaje formateado para ToDus.
    """
    # Formatear textos
    response_text = format_for_todus(response_text) if response_text else ""
    think_text = clean_markdown(think_text) if think_text else ""
    
    # Limitar pensamiento si es muy largo
    if len(think_text) > 300:
        think_text = think_text[:297] + "..."
    
    # Construir mensaje según el estado
    if is_done:
        # Mensaje final completo
        if has_think and think_text:
            message = (
                f"**🧠 Pensamiento:**\n"
                f"> {think_text}\n\n"
                f"---\n\n"
                f"**💬 Respuesta:**\n\n"
                f"{response_text}\n\n"
                f"---\n\n"
                f"*✅ Respuesta completa*"
            )
        else:
            message = (
                f"**💬 Respuesta:**\n\n"
                f"{response_text}\n\n"
                f"---\n\n"
                f"*✅ Respuesta completa*"
            )
    elif has_think and think_text:
        # Mostrando pensamiento + respuesta en progreso
        message = (
            f"**🧠 Pensando...**\n"
            f"> {think_text}\n\n"
            f"---\n\n"
            f"**💬 Respondiendo:**\n\n"
            f"{response_text}\n\n"
            f"*⏳ Generando...*"
        )
    elif response_text:
        # Solo respuesta en progreso (sin pensamiento visible)
        message = (
            f"**💬 Respondiendo:**\n\n"
            f"{response_text}\n\n"
            f"*⏳ Generando...*"
        )
    else:
        # Estado inicial: solo pensando
        message = "🤔 **Pensando...**"
    
    # Limitar longitud máxima
    if len(message) > 4000:
        message = message[:3997] + "..."
    
    return message


def update_message(client, to_phone: str, msg_id: str, 
                   response_text: str, think_text: str = "",
                   has_think: bool = False, is_done: bool = False):
    """
    Actualiza el mensaje con el contenido actual.
    Se llama CADA VEZ que llega un fragmento nuevo.
    """
    message = build_message(response_text, think_text, has_think, is_done)
    
    try:
        client.edit_message(to_phone, message, msg_id)
    except Exception as e:
        logger.error(f"❌ Error actualizando mensaje: {e}")

# ============================================================
# GESTOR GLOBAL DE SESIONES
# ============================================================

session_manager = SessionManager()

# ============================================================
# COMANDO PRINCIPAL
# ============================================================

def handle_ds(client, message: dict):
    """
    Maneja el comando 'ds' - Chat con DeepSeek AI.
    
    FLUJO OPTIMIZADO:
    1. Mensaje inicial: "🤔 Pensando..."
    2. CADA fragmento de 'think' actualiza el mensaje
    3. CADA fragmento de 'response' actualiza el mensaje
    4. 'done' muestra el mensaje final completo
    """
    sender = message.get('from')
    if not sender:
        return
    
    sender_phone = sender.split('@')[0]
    body = message.get('body', '').strip()
    
    # Extraer comando y mensaje
    parts = body.split(maxsplit=1)
    command = parts[0].lower() if parts else ""
    prompt = parts[1] if len(parts) > 1 else ""
    
    # ============================================================
    # COMANDOS ESPECIALES (solo con /)
    # ============================================================
    
    if command == '/new':
        session = session_manager.reset_session(sender_phone)
        client.send_message(
            sender_phone,
            f"**🆕 Nueva sesión creada**\n\n"
            f"ID: `{session.get('session_id', '')[:8]}`...\n"
            f"🧠 DeepThink: ✅ Siempre activo\n"
            f"🔍 Búsqueda: ✅ Siempre activa\n\n"
            f"*Envía cualquier mensaje para comenzar a chatear.*"
        )
        return
    
    elif command == '/clear':
        client.send_message(
            sender_phone,
            "🧹 **Historial limpiado**\n\n"
            "*La sesión sigue activa pero el historial se ha reiniciado.*"
        )
        return
    
    elif command == '/help':
        help_msg = (
            f"**🤖 AIDUS - Asistente IA**\n\n"
            f"**📌 Uso:**\n"
            f"`ds <mensaje>` - Pregunta cualquier cosa\n\n"
            f"**📋 Comandos:**\n"
            f"+ `/new` - Nueva sesión\n"
            f"+ `/clear` - Limpiar historial\n"
            f"+ `/help` - Esta ayuda\n\n"
            f"**🧠 Siempre activo:**\n"
            f"+ Pensamiento profundo\n"
            f"+ Búsqueda web\n\n"
            f"**💡 Ejemplos:**\n"
            f"• `ds ¿Cuál es la capital de Francia?`\n"
            f"• `ds ¿Cómo está el clima hoy?`\n"
            f"• `ds Explícame qué es la IA`\n\n"
            f"*🔧 La sesión se mantiene activa hasta que la reinicies*\n"
            f"*📝 AIDUS nunca genera código y siempre responde en español*"
        )
        client.send_message(sender_phone, help_msg)
        return
    
    # ============================================================
    # SI EMPIEZA CON / PERO NO ES COMANDO VÁLIDO
    # ============================================================
    
    if command.startswith('/'):
        client.send_message(
            sender_phone,
            f"**❌ Comando no reconocido**\n\n"
            f"Comandos disponibles: `/new`, `/clear`, `/help`\n\n"
            f"*Para preguntar algo, solo escribe `ds <mensaje>`*"
        )
        return
    
    # ============================================================
    # SI NO HAY MENSAJE
    # ============================================================
    
    if not prompt:
        help_msg = (
            f"**🤖 AIDUS - Asistente IA**\n\n"
            f"Envía `ds <mensaje>` para preguntar cualquier cosa.\n"
            f"Usa `ds /help` para ver los comandos disponibles."
        )
        client.send_message(sender_phone, help_msg)
        return
    
    # ============================================================
    # PROCESAR PREGUNTA NORMAL
    # ============================================================
    
    # Obtener o crear sesión
    session_manager.get_or_create_session(sender_phone)
    ds_client = session_manager.get_client(sender_phone)
    
    if not ds_client:
        client.send_message(sender_phone, "❌ Error al crear sesión. Usa `/new` para intentar de nuevo.")
        return
    
    try:
        # 1. Mensaje inicial: "🤔 Pensando..."
        msg_id = client.send_message(sender_phone, "🤔 **Pensando...**")
        
        # Variables de streaming
        full_response = ""
        full_think = ""
        has_think = False
        fragment_count = 0
        
        # 2. Procesar eventos de DeepSeek
        for event_type, content, msg_id_ds in ds_client.send_message(prompt):
            fragment_count += 1
            
            if event_type == 'think':
                full_think += content
                has_think = True
                # ✅ ACTUALIZAR INMEDIATAMENTE con el fragmento de pensamiento
                update_message(
                    client, sender_phone, msg_id,
                    full_response, full_think,
                    has_think=has_think,
                    is_done=False
                )
            
            elif event_type == 'response':
                full_response += content
                # ✅ ACTUALIZAR INMEDIATAMENTE con el fragmento de respuesta
                update_message(
                    client, sender_phone, msg_id,
                    full_response, full_think,
                    has_think=has_think,
                    is_done=False
                )
            
            elif event_type == 'done':
                # ✅ Mensaje final completo
                update_message(
                    client, sender_phone, msg_id,
                    full_response, full_think,
                    has_think=has_think,
                    is_done=True
                )
                break
            
            elif event_type == 'error':
                client.send_message(
                    sender_phone,
                    f"**❌ Error en AIDUS**\n\n"
                    f"{content}\n\n"
                    f"*Usa `/new` para reiniciar la sesión.*"
                )
                return
        
        # Actualizar contador
        session = session_manager.sessions.get(sender_phone)
        if session:
            session['message_count'] = session.get('message_count', 0) + 1
            session['last_message'] = prompt
        
        logger.info(f"✅ Mensaje procesado para {sender_phone}: {len(full_response)} caracteres, {fragment_count} fragmentos")
        
    except Exception as e:
        logger.error(f"❌ Error en handle_ds: {e}")
        client.send_message(
            sender_phone,
            f"**❌ Error inesperado**\n\n"
            f"{str(e)[:150]}\n\n"
            f"*Usa `/new` para reiniciar la sesión.*"
        )


def handle_ds_help(client, message: dict):
    """Envía ayuda sobre el comando ds."""
    sender = message.get('from')
    if not sender:
        return
    
    sender_phone = sender.split('@')[0]
    
    help_msg = (
        f"**🤖 AIDUS - Asistente IA**\n\n"
        f"**📌 Uso:**\n"
        f"`ds <mensaje>` - Pregunta cualquier cosa\n\n"
        f"**📋 Comandos:**\n"
        f"+ `/new` - Nueva sesión\n"
        f"+ `/clear` - Limpiar historial\n"
        f"+ `/help` - Esta ayuda\n\n"
        f"**🧠 Siempre activo:**\n"
        f"+ Pensamiento profundo\n"
        f"+ Búsqueda web\n\n"
        f"**💡 Ejemplos:**\n"
        f"• `ds ¿Cuál es la capital de Francia?`\n"
        f"• `ds ¿Cómo está el clima hoy?`\n"
        f"• `ds Explícame qué es la IA`\n\n"
        f"---\n\n"
        f"*🔧 La sesión se mantiene activa hasta que la reinicies*\n"
        f"*📝 AIDUS nunca genera código y siempre responde en español*"
    )
    
    try:
        client.send_message(sender_phone, help_msg)
        logger.info(f"✅ Ayuda de ds enviada a {sender_phone}")
    except Exception as e:
        logger.error(f"❌ Error enviando ayuda de ds: {e}")