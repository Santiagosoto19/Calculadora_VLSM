#!/usr/bin/env bash
# Configura el entorno virtual local y lanza Slicer.
# Uso:
#   ./setup.sh              # instala deps y abre Streamlit en 127.0.0.1:8501
#   ./setup.sh --cli -- ipv4 192.168.10.0/24 -s LAN:100 -s WAN:2
#   ./setup.sh --cli -- ipv6 2001:db8:abcd::/48 --prefix 64 --count 4
#   ./setup.sh --install-only
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-$ROOT/.venv}"
HOST="${VLSM_HOST:-127.0.0.1}"
PORT="${VLSM_PORT:-8501}"

MODE="app"
INSTALL_ONLY=0
CLI_ARGS=()

usage() {
  cat <<'EOF'
setup.sh — entorno local de Slicer

  ./setup.sh                 Crea .venv, instala requirements y abre Streamlit
  ./setup.sh --install-only  Solo crea el venv e instala dependencias
  ./setup.sh --cli -- …      Ejecuta cli.py con los argumentos posteriores a --
  ./setup.sh --help          Esta ayuda

Variables opcionales: PYTHON_BIN, VENV_DIR, VLSM_HOST, VLSM_PORT
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cli) MODE="cli"; shift ;;
    --install-only) INSTALL_ONLY=1; shift ;;
    --help|-h) usage; exit 0 ;;
    --) shift; CLI_ARGS+=("$@"); break ;;
    *) CLI_ARGS+=("$1"); shift ;;
  esac
done

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "No se encontró $PYTHON_BIN. Instale Python 3.10 o superior." >&2
  exit 1
fi

PY_VERSION="$("$PYTHON_BIN" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "Se requiere Python 3.10+. Detectado: $PY_VERSION" >&2
  exit 1
fi

if [[ ! -d "$VENV_DIR" ]]; then
  echo "Creando entorno virtual en $VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

VENV_PY="$VENV_DIR/bin/python"
if [[ ! -x "$VENV_PY" ]]; then
  echo "El venv no contiene un intérprete en $VENV_PY" >&2
  exit 1
fi

"$VENV_PY" -m pip install --upgrade pip
"$VENV_PY" -m pip install -r "$ROOT/requirements.txt"

echo "Entorno listo (Python $PY_VERSION, venv=$VENV_DIR)"

if [[ "$INSTALL_ONLY" -eq 1 ]]; then
  echo "Instalación completada. Active con: source $VENV_DIR/bin/activate"
  exit 0
fi

if [[ "$MODE" == "cli" ]]; then
  exec "$VENV_PY" "$ROOT/cli.py" "${CLI_ARGS[@]}"
fi

echo "Iniciando Streamlit en http://${HOST}:${PORT} (solo localhost)"
exec "$VENV_PY" -m streamlit run "$ROOT/app.py" \
  --server.address="$HOST" \
  --server.port="$PORT" \
  --server.headless=true \
  --browser.gatherUsageStats=false
