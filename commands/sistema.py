#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Comandos de administración del propio bot (recarga de comandos)."""

import logging

from core.context import CommandContext
from core.registry import command, reload_commands

logger = logging.getLogger("bot.commands.sistema")


@command("reload", aliases=["recargar"], help="Vuelve a leer la carpeta commands/ sin reiniciar el bot")
def handle_reload(ctx: CommandContext) -> None:
    count = reload_commands("commands")
    logger.warning("Comandos recargados por %s (%s archivos).", ctx.sender_phone, count)
    ctx.reply(f"🔄 Comandos recargados: {count} archivos leídos desde commands/.")
