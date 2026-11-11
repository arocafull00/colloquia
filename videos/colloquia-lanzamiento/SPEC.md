GOAL:    El psicólogo entiende en 30 s que con Colloquia pulsa Grabar, hace su sesión y recibe la transcripción literal
         (dos voces, pausas medidas, palabras dudosas) sin que el audio salga de su ordenador. Quiere descargarlo.
OUTPUT:  HyperFrames, 1920 x 1080, 30 fps
TIME:    30 s x 30 fps = 900 frames; rejilla de 120 BPM (pista de Dicto) = 15 frames por pulso, un compás = 2 s
LOOK:    La paleta de la app (ui.html): ciruela #493C55, marfil #F4F1EC, tinta #26212C, bruma #E7DFE8, panel #faf8f5.
         Acento claro sobre oscuro: lila #c9b9d6. Estados reales: grabar #e5484d, dudosa #f5a524, segunda voz #d39233.
         Display: Inter 900, 150-180 px, tracking -4.5%. Secundario: Inter 700 40-56 px.
         Medio: la UI real de Colloquia (ui.html) reconstruida a 2x: vista Grabando, Procesando, Sesión guardada y la
         transcripción. Sesión ficticia (el ejemplo del README). Sombras: 0 40px 80px rgba(38,33,44,.28). Sin grano ni brillos.
OBJECTS: El botón Grabar real (marfil, punto rojo), el temporizador 00:00:00, la onda de barras blancas sobre ciruela,
         las dos comillas del símbolo y el wordmark reales (packaging/logo-color.svg).
MOTION:  Llegada expo.out / power4.out; cámara power2.inOut; salidas power3.in. Movimientos 0.3-0.5 s con blur 8-16 px.
         Títulos: blur-in por palabra, quietos al aterrizar.
SHOTS:
  A  0.0-5.0   Gancho. Botón Grabar a 3x sobre marfil, el cursor lo pulsa (0.45) "Graba." -> el punto rojo se convierte
               en el temporizador que corre hasta 00:52:14 "Atiende." -> Detener (2.0) "Lee." -> las dos comillas se
               cierran en el centro (3.0) + wordmark + "Tus sesiones, transcritas en tu ordenador".
  B  5.0-13.0  La app. Ventana real: vista Grabando (temporizador en cámara rápida, onda viva, Pausar/Detener).
               Cursor pulsa Detener (7.2) -> Procesando: cinco pasos reales que se marcan, % sube (7.6-10.2) ->
               Sesión guardada: sesion.mp3 + transcripcion.txt, dos voces con su frase, botón Ver transcripción (12.4).
  C 13.0-21.0  La prueba: la transcripción a 2x. Cuatro turnos aparecen con su hora. Etiquetas que nombran lo que pasa:
               "Dos voces" (14.2), "Silencios medidos" (15.6), "Palabras dudosas" (17.0), "Lo que se oye" (18.4).
               Push final sobre "Pacue[?]" y la página sube como fondo tinta.
  D 21.0-24.5  Privacidad sobre tinta: "Nada sale de tu consulta" + onda + "Sin nube · Sin telemetría · Sin internet".
  E 24.5-30.0  Cierre en marfil: lockup ciruela, "Tú atiendes. Colloquia toma las notas.", botón Descargar,
               plataformas, repo. Hold 2.5 s.
BANNED:  fondo oscuro vacío con cosas pequeñas flotando; glow, partículas, gradientes morados; tres tarjetas en fila;
         título sobre captura oscurecida; logo en una esquina; todo entrando con fade + slide-up; títulos que se mueven
         tras aterrizar; datos de pacientes reales; "Presentamos"; claims que el README no hace (nada de "IA que
         entiende", ni "100 % exacta", ni "código abierto": el repo no tiene licencia).
QA:      0.0, 1.0, 2.3, 3.6, 5.4, 6.8, 8.6, 10.6, 12.2, 13.6, 14.6, 16.0, 17.4, 18.8, 20.6, 22.4, 26.0, 29.8.
