#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Comandos básicos del bot: bienvenida, ayuda, ping, id y estadísticas."""

import time
from datetime import datetime

from core import config
from core.context import CommandContext
from core.registry import command, registry

_START_TIME = time.time()


@command("start", help="Muestra el mensaje de bienvenida")
def handle_start(ctx: CommandContext) -> None:
    prefix = config.PREFIXES[0]
    ctx.reply(
        "🎉 ¡Hola! Bienvenido al bot de ToDus.\n\n"
        "Puedes enviarme comandos y responderé.\n"
        f"Escribe {prefix}help para ver todo lo que puedo hacer."
    )


@command("help", aliases=["ayuda", "comandos"], help="Muestra la lista de comandos disponibles")
def handle_help(ctx: CommandContext) -> None:
    prefix = config.PREFIXES[0]

    if ctx.args:
        # Ayuda de un comando específico: "help yt"
        target = registry.resolve(ctx.args[0])
        if not target:
            ctx.reply_error(f"No existe el comando '{ctx.args[0]}'.")
            return
        lines = [f"📌 {prefix}{target.name}"]
        if target.aliases:
            lines.append(f"Alias: {', '.join(target.aliases)}")
        if target.usage:
            lines.append(f"Uso: {prefix}{target.usage}")
        lines.append(target.help or "Sin descripción.")
        ctx.reply("\n".join(lines))
        return

    visible = [c for c in registry.all() if not c.hidden]
    lines = ["📋 Comandos disponibles:\n"]
    for spec in visible:
        desc = f" — {spec.help}" if spec.help else ""
        lines.append(f"• {prefix}{spec.name}{desc}")
    lines.append(f"\nEscribe {prefix}help <comando> para más detalle de uno en particular.")
    ctx.reply("\n".join(lines))


@command("ping", help="Comprueba que el bot está respondiendo")
def handle_ping(ctx: CommandContext) -> None:
    ctx.reply("🏓 pong")


@command("id", help="Muestra tu número de teléfono tal como lo ve el bot")
def handle_id(ctx: CommandContext) -> None:
    ctx.reply(f"🪪 Tu número: {ctx.sender_phone}")


@command("time", aliases=["hora"], help="Muestra la fecha y hora actuales del servidor")
def handle_time(ctx: CommandContext) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ctx.reply(f"🕒 {now}")


@command("echo", help="Repite el texto que le envíes", usage="echo <texto>")
def handle_echo(ctx: CommandContext) -> None:
    if not ctx.raw_args:
        ctx.reply_error("Escribe algo después del comando, ej: echo hola")
        return
    ctx.reply(ctx.raw_args)


@command("stats", aliases=["estado"], help="Muestra estadísticas del bot y del anti-spam")
def handle_stats(ctx: CommandContext) -> None:
    uptime_seconds = int(time.time() - _START_TIME)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    lines = [
        "📊 Estado del bot",
        f"⏱️ Tiempo activo: {hours}h {minutes}m {seconds}s",
        f"📦 Comandos cargados: {len(registry)}",
    ]

    antispam = getattr(ctx, "_antispam_stats", None)
    if antispam:
        lines.append(f"🛡️ Mensajes procesados: {antispam.get('total_processed', 0)}")
        lines.append(f"🚫 Duplicados bloqueados: {antispam.get('duplicates_blocked', 0)}")

    ctx.reply("\n".join(lines))
