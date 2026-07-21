#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Comando para interactuar con DeepSeek AI en ToDus.
Flujo simplificado:
- DeepThink y búsqueda siempre activos por defecto
- Cualquier texto sin / es una pregunta para la IA
- Comandos especiales solo con prefijo /
"""

import re
import logging
import time
from typing import Dict, Optional
from datetime import datetime

# Importar el cliente DeepSeek
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from dnsn import DeepSeekClient

logger = logging.getLogger(__name__)

# ============================================================
# CONFIGURACIÓN
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
        
        # DeepThink y búsqueda SIEMPRE activos por defecto
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
            # Mantener DeepThink y búsqueda activos
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
# PROCESAMIENTO DE TEXTO
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
    """Formatea texto para ToDus."""
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


def update_stream_message(client, to_phone: str, msg_id: str, 
                          response_text: str, think_text: str = "",
                          is_done: bool = False):
    """Actualiza el mensaje en streaming."""
    if not response_text and not think_text:
        return
    
    response_text = format_for_todus(response_text)
    think_text = clean_markdown(think_text) if think_text else ""
    
    if len(think_text) > 300:
        think_text = think_text[:297] + "..."
    
    if is_done:
        if think_text:
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
    else:
        if think_text:
            message = (
                f"**🧠 Pensando...**\n"
                f"> {think_text}\n\n"
                f"---\n\n"
                f"**💬 Respondiendo:**\n\n"
                f"{response_text}\n\n"
                f"*⏳ Generando...*"
            )
        else:
            message = (
                f"**💬 Respondiendo:**\n\n"
                f"{response_text}\n\n"
                f"*⏳ Generando...*"
            )
    
    if len(message) > 4000:
        message = message[:3997] + "..."
    
    try:
        client.edit_message(to_phone, message, msg_id)
    except Exception as e:
        logger.error(f"❌ Error actualizando mensaje: {e}")

# ============================================================
# COMANDO PRINCIPAL
# ============================================================

session_manager = SessionManager()


def handle_ds(client, message: dict):
    """
    Maneja el comando 'ds' - Chat con DeepSeek AI.
    
    FLUJO SIMPLIFICADO:
    - ds <mensaje> → Pregunta a la IA (DeepThink y búsqueda SIEMPRE activos)
    - ds /new → Nueva sesión
    - ds /clear → Limpiar historial
    - ds /help → Ayuda
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
            f"*🔧 La sesión se mantiene activa hasta que la reinicies*"
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
        # Mensaje inicial
        initial_msg = (
            f"**🤖 AIDUS procesando...**\n\n"
            f"📝 {prompt[:50]}{'...' if len(prompt) > 50 else ''}\n\n"
            f"*⏳ Generando respuesta con DeepThink y búsqueda...*"
        )
        msg_id = client.send_message(sender_phone, initial_msg)
        
        # Variables de streaming
        full_response = ""
        full_think = ""
        last_update = time.time()
        update_interval = 1.0
        
        # Enviar a DeepSeek
        for event_type, content, msg_id_ds in ds_client.send_message(prompt):
            if event_type == 'think':
                full_think += content
                if time.time() - last_update >= update_interval:
                    update_stream_message(client, sender_phone, msg_id, full_response, full_think)
                    last_update = time.time()
            
            elif event_type == 'response':
                full_response += content
                if time.time() - last_update >= update_interval:
                    update_stream_message(client, sender_phone, msg_id, full_response, full_think)
                    last_update = time.time()
            
            elif event_type == 'done':
                update_stream_message(client, sender_phone, msg_id, full_response, full_think, is_done=True)
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
        
        logger.info(f"✅ Mensaje procesado para {sender_phone}: {len(full_response)} caracteres")
        
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