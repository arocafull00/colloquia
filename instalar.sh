#!/bin/bash
cd "$(dirname "$0")" || exit 1
HERE="$(pwd)"

echo
echo "  Colloquia · instalación"
echo "  ───────────────────────"
echo

fail() {
    echo
    echo "  Algo ha fallado durante la instalación. Revisa los mensajes de arriba."
    exit 1
}

PY=""
for c in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys, venv; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
        PY="$c"
        break
    fi
done
if [ -z "$PY" ]; then
    echo "  No se ha encontrado Python 3.10 o superior con venv."
    echo "  En Debian/Ubuntu:  sudo apt install python3 python3-venv libportaudio2 libxcb-cursor0"
    echo "  En Fedora:         sudo dnf install python3 portaudio xcb-util-cursor"
    echo "  En Arch:           sudo pacman -S python portaudio xcb-util-cursor"
    exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
    echo "  [1/3] Creando el entorno de Python..."
    "$PY" -m venv .venv || fail
else
    echo "  [1/3] Entorno de Python ya creado."
fi

echo "  [2/3] Instalando dependencias. Puede tardar unos minutos..."
.venv/bin/python -m pip install --upgrade pip --quiet --disable-pip-version-check
.venv/bin/python -m pip install -r requirements.txt --disable-pip-version-check || fail
if ! .venv/bin/python -c "import sounddevice" >/dev/null 2>&1; then
    echo
    echo "  Falta la biblioteca de audio PortAudio. Instálala y vuelve a ejecutar este script:"
    echo "  En Debian/Ubuntu:  sudo apt install libportaudio2"
    echo "  En Fedora:         sudo dnf install portaudio"
    echo "  En Arch:           sudo pacman -S portaudio"
    exit 1
fi

echo "  [3/3] Creando el acceso en el menú de aplicaciones..."
DESKTOP="${XDG_DATA_HOME:-$HOME/.local/share}/applications/colloquia.desktop"
mkdir -p "$(dirname "$DESKTOP")"
cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=Colloquia
Comment=Grabación y transcripción local de sesiones
Exec="$HERE/.venv/bin/python" "$HERE/colloquia.py"
Path=$HERE
Icon=audio-input-microphone
Terminal=false
Categories=AudioVideo;Audio;Recorder;
EOF

echo
echo "  La primera vez Colloquia descarga los modelos (~1,7 GB con el modelo Turbo)."
echo "  Después funciona sin conexión a internet."
echo
echo "  Listo. Abre Colloquia desde el menú de aplicaciones o con:"
echo "  $HERE/.venv/bin/python $HERE/colloquia.py"
nohup .venv/bin/python colloquia.py >/dev/null 2>&1 &
