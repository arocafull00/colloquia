#!/bin/bash
cd "$(dirname "$0")" || exit 1
HERE="$(pwd)"

echo
echo "  Colloquia · instalación"
echo "  ───────────────────────"
echo

finish() {
    echo
    read -n 1 -s -r -p "  Pulsa una tecla para cerrar."
    echo
    exit "$1"
}

fail() {
    echo
    echo "  Algo ha fallado durante la instalación. Revisa los mensajes de arriba."
    finish 1
}

PY=""
for c in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys, tkinter; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
        PY="$c"
        break
    fi
done
if [ -z "$PY" ]; then
    echo "  No se ha encontrado Python 3.10 o superior con Tkinter."
    echo "  Instálalo desde https://www.python.org/downloads/macos/"
    echo "  (o con Homebrew: brew install python@3.12 python-tk@3.12)"
    echo "  y vuelve a ejecutar este instalador."
    finish 1
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

echo "  [3/3] Creando Colloquia.app..."
APP="$HOME/Applications/Colloquia.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" || fail
cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>Colloquia</string>
    <key>CFBundleDisplayName</key><string>Colloquia</string>
    <key>CFBundleIdentifier</key><string>io.github.arocafull00.colloquia</string>
    <key>CFBundleExecutable</key><string>Colloquia</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>NSMicrophoneUsageDescription</key><string>Colloquia usa el micrófono para grabar las sesiones.</string>
</dict>
</plist>
EOF
LOG="$HOME/Library/Application Support/Colloquia/colloquia.log"
mkdir -p "$(dirname "$LOG")"
cat > "$APP/Contents/MacOS/Colloquia" <<EOF
#!/bin/sh
cd "$HERE"
exec "$HERE/.venv/bin/python" "$HERE/colloquia.py" >> "$LOG" 2>&1
EOF
chmod +x "$APP/Contents/MacOS/Colloquia"
open "$APP"

echo
echo "  La primera vez Colloquia descarga los modelos (~1,7 GB con el modelo Turbo)."
echo "  Después funciona sin conexión a internet."
echo
echo "  macOS te pedirá permiso para usar el micrófono: concédelo."
echo
echo "  Listo. A partir de ahora abre Colloquia desde Spotlight, Launchpad o ~/Applications."
finish 0
