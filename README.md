# Colloquia

Grabación y transcripción **local** de sesiones largas (una hora o más) entre psicólogo y paciente.

Pulsas **Grabar**, haces la sesión y pulsas **Detener**. Colloquia guarda en la carpeta que elijas:

- `sesion.mp3`: la grabación completa (64 kbps mono, unos 30 MB por hora).
- `transcripcion.txt`: la transcripción **literal**, con marcas de tiempo, separando las dos voces (Psicólogo/Paciente) y marcando silencios, pausas y palabras dudosas.

Nada sale del ordenador: no usa servicios en la nube ni telemetría. Los modelos se descargan una sola vez y después funciona sin conexión.

## Transcripción literal

Colloquia está pensada para sesiones en las que importa **cómo** se habla, no solo qué se dice; por ejemplo, con niños que se equivocan al hablar. Por eso:

- Conserva las muletillas (*eh*, *mmm*), las repeticiones (*yo… yo fui*), los cortes (*Ma… mamá*) y las palabras mal pronunciadas que reconoce (*pakue*, *pelo* por *perro*).
- Mide los silencios directamente sobre el audio y los marca:
  ```
  [00:00:03] (silencio 1,7 s)
  [00:00:05] Paciente: Eh... (pausa 1,6 s) yo... yo fui al... al Pacue... mmm[?]... (pausa 2,2 s) con mi mamá.
  ```
  - `(pausa X s)`: silencio dentro de una intervención.
  - `(silencio X s)` en su propia línea: silencio entre intervenciones, es decir, el tiempo de respuesta.
  - El umbral se configura en Ajustes (1, 1,5, 2 o 3 s).
- Marca con `palabra[?]` las palabras que el modelo reconoce con poca seguridad. Suelen ser palabras mal pronunciadas o poco claras, y conviene escucharlas en el MP3.

> **Limitación importante:** Whisper, el modelo de transcripción, se entrenó para producir texto legible. Aunque Colloquia lo fuerza a transcribir de forma literal, a veces sigue «corrigiendo» una palabra mal pronunciada por la correcta (por ejemplo *gande* → *grande*). La transcripción sirve de guía y el MP3 es la referencia: para un análisis fino del habla, revisa los fragmentos marcados con `[?]` escuchando el audio.

## Identificación de las voces

- Se detectan automáticamente dos voces.
- La de quien habla primero se asigna al psicólogo.
- Al terminar, Colloquia muestra una frase de cada voz y un botón **Intercambiar** por si lo asignó al revés.
- Los nombres de los roles se cambian en Ajustes.

## Instalación

Descarga el instalador de tu sistema desde la página de *Releases* del repositorio. No hace falta instalar Python.

### Windows

Descarga `Colloquia-Windows-Setup.exe`. Sirve para cualquier equipo: si hay una GPU NVIDIA la usa para transcribir mucho más rápido y, si no, funciona con la CPU.

El instalador:
- no pide permisos de administrador; instala en `%LOCALAPPDATA%\Programs\Colloquia`;
- crea un acceso en el menú Inicio y, si lo marcas, en el escritorio.

Como el instalador no está firmado, Windows SmartScreen puede avisar: pulsa **Más información** → **Ejecutar de todas formas**.

### macOS (Apple Silicon)

1. Abre `Colloquia-…-macos-arm64.dmg` y arrastra **Colloquia** a **Aplicaciones**.
2. La app no está firmada por Apple, así que la primera vez macOS la bloquea. Ve a **Ajustes del Sistema → Privacidad y seguridad** y pulsa **Abrir igualmente**.
3. macOS pedirá permiso para usar el micrófono: concédelo.

### Linux

- `Colloquia-…-linux-x86_64.AppImage`: dale permiso de ejecución (`chmod +x`) y ábrelo.
- `Colloquia-…-linux-x86_64.tar.gz`: descomprímelo y ejecuta `Colloquia/Colloquia`.

Si no detecta el micrófono, instala PortAudio desde tu distribución (por ejemplo, `sudo apt install libportaudio2`).

### Desde el código fuente

Necesitas Python 3.10 o superior.

- **Windows:** doble clic en `instalar.bat`. Si hay una GPU NVIDIA, instala el soporte CUDA, y crea accesos directos en el menú Inicio y en el escritorio.
- **macOS:** doble clic en `instalar.command`. Crea `~/Applications/Colloquia.app`.
- **Linux:** instala las dependencias del sistema y ejecuta el script; crea un acceso en el menú de aplicaciones.
  ```bash
  sudo apt install python3 python3-venv python3-tk libportaudio2
  ```
  ```bash
  ./instalar.sh
  ```

### Modelos y equipos sin conexión

La primera vez se descargan unos 1,7 GB con el modelo Turbo:
- el modelo de transcripción, desde Hugging Face, en `~/.cache/huggingface`;
- los modelos de voces, desde GitHub, en la carpeta de configuración de Colloquia.

Para instalar en un equipo sin internet, copia los modelos en una carpeta `models/` junto a la aplicación: junto a `Colloquia.exe`, `Colloquia.app` o el `.AppImage` en las versiones instaladas, o junto a `colloquia.py` si usas el código fuente.

```
models/
  faster-whisper-large-v3-turbo/   (model.bin, config.json, tokenizer.json…)
  sherpa-onnx-pyannote-segmentation-3-0/model.onnx
  3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx
```

## Tiempo de procesado

Procesar una sesión de una hora tarda aproximadamente:

| Equipo | Modelo | Tiempo aproximado |
|---|---|---|
| GPU NVIDIA | Turbo (recomendado) | 5–10 min |
| Solo CPU | Turbo | 30–60 min |
| Solo CPU | Medium / Small | 20–40 min |

La transcripción y la identificación de voces se hacen en paralelo.

## Seguridad de la grabación

- El audio se escribe en disco de forma continua. Si el ordenador se apaga o la app se cierra en mitad de una sesión, al volver a abrirla aparecerá «Hay una grabación sin procesar» con un botón para procesarla.
- Mientras graba o procesa, el equipo no entra en suspensión.
- Si el micrófono deja de captar sonido durante 30 s, la app avisa.

## Privacidad

- Las grabaciones de sesiones clínicas son datos de salud. Pide el consentimiento informado del paciente o de sus tutores antes de grabar.
- Los archivos se guardan sin cifrar en la carpeta elegida. Usa un disco cifrado (BitLocker, FileVault, LUKS) o una carpeta protegida.

## Procesar un audio existente

Con la versión instalada:
- Windows: `colloquia-cli.exe grabacion.mp3 carpeta_salida`, desde la carpeta de instalación.
- macOS: `/Applications/Colloquia.app/Contents/MacOS/Colloquia grabacion.mp3 carpeta_salida`.
- Linux: `./Colloquia-…-linux-x86_64.AppImage grabacion.mp3 carpeta_salida`.

Desde el código fuente:

```bash
.venv/bin/python pipeline.py grabacion.mp3 carpeta_salida
```

En Windows, usa `.venv\Scripts\python.exe`.

## Compilar los instaladores

Los instaladores se generan con PyInstaller a partir de `packaging/colloquia.spec`. Desde el entorno con las dependencias instaladas:

```bash
pip install pyinstaller pillow
```

```bash
pyinstaller --noconfirm packaging/colloquia.spec
```

- El resultado queda en `dist/`: `Colloquia/` en Windows y Linux, `Colloquia.app` en macOS.
- En Windows, con la variable `COLLOQUIA_CUDA=1` se incluyen las DLL de CUDA (cuBLAS y cuDNN) de los paquetes `nvidia-*`. Sin ella, la aplicación usa solo la CPU.
- El instalador de Windows se crea con Inno Setup: `iscc packaging\colloquia.iss`.
- El flujo `.github/workflows/build.yml` compila Windows (con CUDA), macOS y Linux. Se ejecuta a mano o al subir una etiqueta `v*`; en ese caso crea un borrador de *release* con los instaladores.

## Configuración

`config.json` está en:
- `%APPDATA%\Colloquia` en Windows;
- `~/Library/Application Support/Colloquia` en macOS;
- `~/.config/colloquia` en Linux.

En esa misma carpeta está el registro de errores, `colloquia.log`.
