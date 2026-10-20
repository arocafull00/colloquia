---
name: release
description: Publica una nueva versión de Colloquia. Crea y sube la etiqueta vX.Y.Z, espera a que GitHub Actions compile los instaladores, publica el borrador de release con notas generadas y comprueba que el enlace de descarga de la landing funciona. Úsala cuando el usuario diga "nueva release", "publica una versión", "saca la v1.2.0" o invoque /release.
argument-hint: "[patch|minor|major|X.Y.Z]"
---

# Publicar una release de Colloquia

El argumento indica la versión: `patch` (por defecto), `minor`, `major` o un número exacto `X.Y.Z`. Que el usuario invoque la skill es la autorización para subir la etiqueta y publicar la release; no pidas confirmación salvo que algo falle o no cuadre.

## 1. Comprobaciones previas

```bash
git fetch origin --tags
git status --porcelain
git rev-parse --abbrev-ref HEAD
git rev-list --left-right --count origin/main...HEAD
```

- Debe estar en `main`. Si no, para y díselo al usuario.
- Si hay cambios sin commit, para y enséñaselos; no los incluyas por tu cuenta.
- Si `main` va por detrás de `origin/main`, para. Si va por delante, sube `main` (`git push origin main`): la etiqueta tiene que apuntar a un commit que esté en GitHub.

## 2. Calcular la versión

```bash
git tag --list "v*" --sort=-v:refname | head -1
```

- Sin etiquetas previas, la primera es `v1.0.0`.
- Aplica `patch`/`minor`/`major` a la última, o usa el número exacto que se haya pasado.
- Si la etiqueta ya existe en local o en `origin`, para y avisa.

## 3. Crear y subir la etiqueta

```bash
git tag -a vX.Y.Z -m "Colloquia X.Y.Z"
git push origin vX.Y.Z
```

Esto lanza `.github/workflows/build.yml`, que compila Windows (CUDA), macOS y Linux y crea un borrador de release con los instaladores, incluido `Colloquia-Windows-Setup.exe`.

## 4. Esperar a la compilación

Busca la ejecución lanzada por la etiqueta (puede tardar unos segundos en aparecer):

```bash
gh run list --workflow build.yml --branch vX.Y.Z --limit 1 --json databaseId,status,url
```

Espera a que termine **en segundo plano**, porque tarda bastante más de 2 minutos:

```bash
gh run watch <id> --exit-status --interval 60
```

Mientras tanto, dile al usuario en una línea que la compilación está en marcha, con el enlace a la ejecución.

Si falla:
- Enseña el resumen del error: `gh run view <id> --log-failed | tail -80`.
- No publiques nada.
- Explica que la etiqueta ya está subida. Tras corregir el problema se puede relanzar con `gh run rerun <id> --failed`, o borrar la etiqueta (`git push origin :refs/tags/vX.Y.Z` y `git tag -d vX.Y.Z`). Borrar la etiqueta solo si el usuario lo pide.

## 5. Revisar el borrador

```bash
gh release view vX.Y.Z --json isDraft,assets --jq '{isDraft, assets: [.assets[] | {name, size}]}'
```

Deben estar `Colloquia-Windows-Setup.exe`, el `-windows-setup.exe` versionado, el `.dmg` de macOS y el `.AppImage` y el `.tar.gz` de Linux. Si falta `Colloquia-Windows-Setup.exe`, para: sin él, el botón de la landing da 404. Si algún archivo pasa de 2 GB, avisa.

## 6. Notas y publicación

Genera las notas en español a partir de los commits desde la etiqueta anterior (`git log --pretty=format:"- %s" vANTERIOR..vX.Y.Z`; en la primera release, todo el historial):

- Redáctalas para psicólogos, no para programadores: qué cambia para ellos, en frases cortas. Omite los cambios internos (CI, refactorizaciones), salvo que no haya otros.
- Termina siempre con este bloque:

```markdown
## Descarga

- **Windows:** `Colloquia-Windows-Setup.exe`. Si Windows muestra «Windows protegió su PC», pulsa «Más información» → «Ejecutar de todas formas».
- **macOS (Apple Silicon):** el archivo `.dmg`.
- **Linux:** el `.AppImage` o el `.tar.gz`.

La primera vez se descargan los modelos de transcripción (unos 1,7 GB). Después funciona sin internet.
```

Guarda las notas en un archivo temporal del scratchpad y publica:

```bash
gh release edit vX.Y.Z --draft=false --latest --title "Colloquia X.Y.Z" --notes-file <archivo>
```

## 7. Comprobar el enlace de la landing

```bash
curl -sIL -o /dev/null -w "%{http_code} %{size_download} %{url_effective}\n" https://github.com/arocafull00/colloquia/releases/latest/download/Colloquia-Windows-Setup.exe
```

Tiene que acabar en `200`. Si no, revisa que la release sea pública, no esté marcada como pre-release y sea la `latest`.

## 8. Informe final

En pocas líneas:
- versión publicada y enlace a la release;
- tamaño del instalador de Windows;
- resultado de la comprobación del enlace;
- cualquier aviso, por ejemplo un asset que falte.
