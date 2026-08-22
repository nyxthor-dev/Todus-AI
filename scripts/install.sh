#!/usr/bin/env bash
# Script de instalacion y arranque para VPS Linux.
# Uso:  bash scripts/install.sh
set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="todus-ai-bot"

cd "$PROJECT_DIR"

echo "==> NyxBot - instalacion en $PROJECT_DIR"

# 1) Virtualenv
if [ ! -d "venv" ]; then
    echo "==> Creando virtualenv..."
    python3 -m venv venv
fi
source venv/bin/activate

# 2) Dependencias
echo "==> Instalando dependencias..."
pip install --upgrade pip
pip install -r requirements.txt

# 3) .env
if [ ! -f ".env" ]; then
    echo "==> Copiando .env.example -> .env"
    cp .env.example .env
    echo "!! EDITA .env con tus credenciales antes de arrancar el bot !!"
fi

# 4) Directorios
mkdir -p data logs

# 5) Verificacion rapida de imports
echo "==> Verificando imports..."
python -c "from bot.core import NyxBot; print('OK')"

echo ""
echo "==> Instalacion completa."
echo ""
echo "Para correr en foreground (pruebas):"
echo "    source venv/bin/activate && python main.py"
echo ""
echo "Para instalar como servicio systemd (auto-arranque):"
echo "    sudo cp scripts/todus-ai-bot.service /etc/systemd/system/"
echo "    sudo systemctl daemon-reload"
echo "    sudo systemctl enable --now todus-ai-bot"
echo "    sudo journalctl -u todus-ai-bot -f   # ver logs"
