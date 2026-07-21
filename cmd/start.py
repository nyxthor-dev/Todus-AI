#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Módulo que maneja el comando 'start' del bot de ToDus.
"""

import logging

logger = logging.getLogger(__name__)


def handle_start(client, message: dict):
    """
    Maneja el comando 'start' - Mensaje de bienvenida.
    
    Args:
        client: Instancia del cliente ToDus.
        message: Diccionario con el mensaje recibido.
    """
    sender = message.get('from')
    if not sender:
        return
    
    sender_phone = sender.split('@')[0]
    
    # Mensaje de bienvenida
    welcome_message = (
        f"🎉 ¡Hola! Bienvenido al bot de ToDus.\n\n"
        f"Estoy aquí para ayudarte. Puedes enviarme mensajes y responderé.\n\n"
        f"📌 Comandos disponibles:\n"
        f"  • start - Este mensaje de bienvenida\n"
        f"  • help - Muestra esta ayuda\n"
        f"  • ping - Responde con 'pong'\n"
        f"  • time - Muestra la hora actual\n"
        f"  • echo <texto> - Repite lo que digas\n\n"
        f"Pronto tendré más funcionalidades. ¡Estate atento! 😊"
    )
    
    try:
        msg_id = client.send_message(sender_phone, welcome_message)
        logger.info(f"✅ Respondido a {sender_phone} (msg_id: {msg_id})")
        
    except Exception as e:
        logger.error(f"❌ Error al enviar mensaje de bienvenida a {sender_phone}: {e}")