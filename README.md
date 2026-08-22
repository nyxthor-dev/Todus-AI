# NyxBot — Bot de toDus con IA

Bot para la plataforma de mensajería cubana **toDus** que se conecta a una API
de IA compatible con OpenAI y responde a los usuarios como si fuera un humano
escribiendo en vivo.

## Características

- **IA por defecto**: `gemini-3.5-flash-lite` (la más rápida disponible en tu API).
- **Streaming con edición**: el bot manda un mensaje `…` y lo va **editando** a
  medida que la IA genera tokens — el usuario lo ve "escribiendo en vivo".
- **Comportamiento humano**:
  - Estado "escribiendo…" (`chat_state: composing`) antes de responder.
  - Presencia "en línea" (punto verde) mantenida automáticamente por el SDK.
  - "Visto" (doble check azul) automático en privado.
  - Delay mínimo antes de responder (configurable).
- **Memoria persistente** por usuario en SQLite — la IA recuerda la conversación.
  - En grupos: memoria separada por `(grupo, usuario)`.
  - En privado: memoria por usuario.
- **Rate limiting**:
  - **Owner** (`54309042`): ilimitado.
  - **Grupos**: 10 llamadas/min por usuario (no-owner).
  - **Privado**: 5 llamadas/min por usuario (no-owner); owner ilimitado.
- **Comandos**:
  - `/chat <texto>` — hablar con la IA (alias: `/ai`, `/ask`)
  - `/reset` — borrar tu historial
  - `/help` — ayuda
  - `/ping` — prueba de vida
  - `/id` — tu número de teléfono
  - `/model` — modelo de IA en uso
  - `/stats` *(owner)* — estadísticas
  - `/broadcast <msg>` *(owner)* — mensaje masivo

## Requisitos

- Python ≥ 3.11
- Cuenta de toDus con **contraseña** (no el código SMS)
- API de IA compatible con OpenAI (base_url + api_key)

## Instalación rápida (VPS Linux)

```bash
# 1) Clonar/copiar el proyecto
cd /opt
git clone <tu-repo> todus-ai-bot   # o scp -r ...
cd todus-ai-bot

# 2) Instalar
bash scripts/install.sh

# 3) EDITAR .env con tus credenciales
nano .env
#   - TODUS_PHONE        (número del bot, ej. 5312345678)
#   - TODUS_PASSWORD     (contraseña de la cuenta toDus)
#   - OWNER_PHONE        (tu número, 54309042)
#   - AI_API_KEY         (ya viene con tu key)
#   - AI_MODEL           (gemini-3.5-flash-lite por defecto)

# 4) Probar en foreground
source venv/bin/activate
python main.py
```

## Arranque como servicio (systemd)

```bash
sudo cp scripts/todus-ai-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now todus-ai-bot

# Ver logs
sudo journalctl -u todus-ai-bot -f

# Parar / reiniciar
sudo systemctl restart todus-ai-bot
sudo systemctl stop todus-ai-bot
```

## Cómo funciona el "parecer humano"

1. **Presencia en línea**: cuando el bot arranca, abre el socket XMPP y envía
   la stanza `presence()` inicial. El SDK mantiene keepalive cada 25s — el
   contacto ve el **punto verde**.

2. **"Escribiendo…"**: antes de mandar la respuesta, el bot llama a
   `send_chat_state(to, "composing")` — el contacto ve "escribiendo…" en su
   chat.

3. **Streaming con edición**: en vez de esperar a que la IA termine, el bot:
   - Manda un primer mensaje `…`
   - Conecta el stream de la API de IA
   - Cada ~180 caracteres (o ~1.2s) **edita** el mensaje con lo acumulado
   - Al final deja el texto completo

4. **"Visto"**: en chat privado, el bot manda `send_read_receipt` para que
   aparezca el doble check azul.

5. **Memoria**: cada `(usuario, sesión)` tiene su historial en SQLite. La IA
   recibe los últimos 20 mensajes como contexto. `/reset` lo limpia.

## Configuración avanzada (`.env`)

| Variable | Default | Descripción |
|---|---|---|
| `TODUS_PHONE` | — | Número del bot |
| `TODUS_PASSWORD` | — | Contraseña toDus |
| `OWNER_PHONE` | — | Tu número (acceso ilimitado) |
| `AI_API_BASE` | `https://vimax-ia.p.jo3.org/v1` | Base URL de tu API |
| `AI_API_KEY` | — | Tu API key |
| `AI_MODEL` | `gemini-3.5-flash-lite` | Modelo a usar |
| `HUMAN_TYPING` | `true` | Mostrar "escribiendo…" |
| `HUMAN_STREAM_EDIT` | `true` | Editar el mensaje en streaming |
| `HUMAN_EDIT_INTERVAL` | `180` | Caracteres entre ediciones |
| `HUMAN_ONLINE` | `true` | Presencia en línea |
| `LIMIT_PRIVATE` | `5` | Req/min de no-owner en privado |
| `LIMIT_GROUP` | `10` | Req/min de no-owner en grupo |
| `MEMORY_MAX_MESSAGES` | `20` | Mensajes por contexto |
| `LOG_LEVEL` | `INFO` | `DEBUG` para más detalle |

## Modelo de IA

Tu API (https://vimax-ia.p.jo3.org) expone estos modelos Gemini:

- `gemini-3.6-flash` — más nuevo, balanceado
- `gemini-3.6-flash-extended` — con contexto extendido
- `gemini-3.5-flash` — balanceado
- `gemini-3.5-flash-extended` — contexto extendido
- **`gemini-3.5-flash-lite`** — el más rápido (default del bot)
- `gemini-3.5-flash-lite-extended` — rápido + contexto largo
- `gemini-3.1-flash-lite` — rápido, generación anterior

Para cambiar de modelo, edita `AI_MODEL` en `.env` y reinicia.

## Comportamiento en grupos

- El bot **solo responde** cuando:
  - Es el **owner** hablando, o
  - Alguien **menciona** el número del bot (`@5312345678 …`), o
  - El mensaje termina con `?` (parece pregunta directa)
- Cada usuario tiene su propia memoria `(grupo, usuario)`.
- Rate limit: 10 llamadas/min por usuario (no-owner).

## Troubleshooting

| Problema | Solución |
|---|---|
| `AuthenticationError` | Revisa `TODUS_PASSWORD`. Si usaste solo SMS, generá una password desde la app toDus. |
| `TokenExpiredError` repetido | El bot re-loguea solo; si persiste, cambiá la contraseña. |
| No recibe mensajes | Verificá que el número sea correcto y que la cuenta no esté bloqueada. |
| La IA no responde | Probá `curl` directo a tu API (ver abajo). |
| El bot aparece "offline" | El keepalive del SDK envía presencia cada 25s; si tu VPS tiene firewall restrictivo, abrí salida a `im.todus.cu:5222`. |

### Probar la API de IA manualmente

```bash
curl -s -X POST "https://vimax-ia.p.jo3.org/v1/chat/completions" \
  -H "Authorization: Bearer sk--f8JuT4hCbGIOSYK5xZk7dwkTLMyVnLqQob2Yb5Wo1Q" \
  -H "Content-Type: application/json" \
  -d '{"model":"gemini-3.5-flash-lite","messages":[{"role":"user","content":"Hola"}]}'
```

### Ver modelos disponibles

```bash
curl -s "https://vimax-ia.p.jo3.org/v1/models" \
  -H "Authorization: Bearer sk--f8JuT4hCbGIOSYK5xZk7dwkTLMyVnLqQob2Yb5Wo1Q" | python -m json.tool
```

## Estructura del proyecto

```
todus-ai-bot/
├── main.py                 # Entry point
├── requirements.txt
├── .env.example            # Template de configuracion
├── README.md
├── bot/
│   ├── __init__.py
│   ├── config.py           # Carga de settings
│   ├── ai_client.py        # Cliente OpenAI-compatible
│   ├── memory.py           # SQLite por usuario
│   ├── rate_limiter.py     # Limites owner/privado/grupo
│   ├── human.py            # Comportamiento humano (typing, edit-stream)
│   ├── commands.py         # Comandos slash
│   └── core.py             # NyxBot - integra todo
├── scripts/
│   ├── install.sh          # Setup para VPS
│   └── todus-ai-bot.service # systemd unit
├── data/                   # SQLite (runtime)
└── logs/                   # Logs (runtime)
```

## Licencia

Uso personal del autor.
