#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
HERE="$(pwd -P)"
LAUNCH=1
SYSTEM_DEPS=1

for arg in "$@"; do
    case "$arg" in
        --no-launch) LAUNCH=0 ;;
        --skip-system-deps) SYSTEM_DEPS=0 ;;
        --help|-h)
            echo "Uso: bash instalar.sh [--no-launch] [--skip-system-deps]"
            echo "Instala Colloquia para tu usuario y crea el acceso en el menú."
            echo "Solo las dependencias del sistema requieren sudo."
            exit 0 ;;
        *) echo "Opción desconocida: $arg" >&2; exit 1 ;;
    esac
done

fail() { echo "  $*" >&2; exit 1; }
trap 'echo "  La instalación no se ha completado. Revisa el error anterior." >&2' ERR
[[ "$(uname -s)" == Linux ]] || fail "Este instalador es para Linux."
[[ "$EUID" -ne 0 ]] || fail "Ejecuta bash instalar.sh sin sudo; se pedirá solo para las dependencias del sistema."

echo "  Colloquia · instalación nativa para Linux"
echo "  [1/4] Dependencias del sistema (GTK, WebKit y PortAudio)..."
if [[ "$SYSTEM_DEPS" == 1 ]]; then
    command -v sudo >/dev/null || fail "Falta sudo. Pide al administrador que instale las dependencias indicadas en README.md y usa --skip-system-deps."
    if command -v apt-get >/dev/null; then
        sudo apt-get update
        sudo apt-get install -y python3 python3-venv python3-gi python3-gi-cairo \
            gir1.2-gtk-3.0 gir1.2-webkit2-4.1 libportaudio2 xdg-utils
    elif command -v dnf >/dev/null; then
        sudo dnf install -y python3 python3-pip python3-gobject gobject-introspection gtk3 webkit2gtk4.1 portaudio xdg-utils
    elif command -v pacman >/dev/null; then
        sudo pacman -S --needed --noconfirm python python-pip python-gobject gtk3 webkit2gtk-4.1 portaudio xdg-utils
    else
        fail "Gestor de paquetes no reconocido. Instala las dependencias de README.md y usa --skip-system-deps."
    fi
fi

# PyGObject must use the distribution's Python ABI, not a custom Python in PATH.
PY=/usr/bin/python3
[[ -x "$PY" ]] || fail "No se encuentra /usr/bin/python3."
"$PY" -c 'import sys, venv; assert sys.version_info >= (3, 10), "Se necesita Python 3.10 o superior"'
"$PY" -c 'import gi; gi.require_version("Gtk", "3.0"); gi.require_version("WebKit2", "4.1"); from gi.repository import Gtk, WebKit2' || \
    fail "Faltan GTK/WebKit o PyGObject para el Python del sistema. Revisa las dependencias de tu distribución."

echo "  [2/4] Entorno de Python y dependencias de Colloquia..."
if [[ -x .venv/bin/python ]] && [[ "$(.venv/bin/python -c 'import sys; print(sys.version_info[:2])')" != "$("$PY" -c 'import sys; print(sys.version_info[:2])')" ]]; then
    fail "El entorno .venv usa otra versión de Python. Renómbralo y vuelve a ejecutar el instalador."
fi
"$PY" -m venv --system-site-packages .venv
.venv/bin/python -m pip install --upgrade pip --disable-pip-version-check
.venv/bin/python -m pip install -r requirements.txt --disable-pip-version-check

echo "  [3/4] Comprobando audio, transcripción e interfaz..."
.venv/bin/python packaging/check_linux.py
if [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
    .venv/bin/python packaging/check_linux.py --gui
else
    echo "  No hay sesión gráfica: queda pendiente comprobar la ventana desde el escritorio."
fi

echo "  [4/4] Creando el comando y el acceso en el menú..."
BIN_DIR="$HOME/.local/bin"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}"
.venv/bin/python - "$HERE" "$BIN_DIR" "$DATA_DIR" <<'PY'
from pathlib import Path
import shlex
import sys

root, bin_dir, data_dir = map(Path, sys.argv[1:])
launcher = bin_dir / "colloquia"
bin_dir.mkdir(parents=True, exist_ok=True)
launcher.write_text(
    "#!/bin/sh\n"
    "export PYWEBVIEW_GUI=gtk\n"
    f"cd -- {shlex.quote(str(root))} || exit 1\n"
    f"exec {shlex.quote(str(root / '.venv/bin/python'))} {shlex.quote(str(root / 'colloquia.py'))} \"$@\"\n",
    encoding="utf-8",
)
launcher.chmod(0o755)

def desktop_exec(path):
    value = str(path)
    for char in ('\\', '"', '`', '$'):
        value = value.replace(char, '\\' + char)
    return '"' + value.replace('\\', '\\\\').replace('%', '%%') + '"'

desktop = data_dir / "applications/colloquia.desktop"
desktop.parent.mkdir(parents=True, exist_ok=True)
icon = str(root / "packaging/colloquia.png").replace('\\', '\\\\')
desktop.write_text(
    "[Desktop Entry]\nType=Application\nName=Colloquia\n"
    "Comment=Grabación y transcripción local de sesiones\n"
    f"Exec={desktop_exec(launcher)}\nIcon={icon}\n"
    "Terminal=false\nCategories=AudioVideo;Audio;Recorder;\n",
    encoding="utf-8",
)
PY
if command -v update-desktop-database >/dev/null; then
    update-desktop-database "$DATA_DIR/applications" || true
fi

echo "  Listo. Abre Colloquia desde el menú de aplicaciones o ejecuta:"
printf '  %q\n' "$BIN_DIR/colloquia"
echo "  No muevas esta carpeta: contiene la aplicación y su entorno."
echo "  La primera vez se descargan los modelos (~1,7 GB con Turbo)."
if [[ "$LAUNCH" == 1 && -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
    LOG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/colloquia"
    mkdir -p "$LOG_DIR"
    nohup "$BIN_DIR/colloquia" >> "$LOG_DIR/colloquia.log" 2>&1 &
fi
