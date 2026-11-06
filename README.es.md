# 🎂 Cumplidora

🇬🇧 [Read in English](./README.md)

Recordatorio local de cumpleaños para Linux sincronizado con **Google Forms + Google Sheets** (para cargar cumpleaños desde el celular en segundos estés donde estés, incluso con tu PC apagada) y notificaciones push por **Bot de Telegram**.

* **Cero dependencias externas:** utiliza únicamente la biblioteca estándar de Python 3.
* **Sin importar el año:** registra solo día y mes (maneja automáticamente el `29/02` tanto en años bisiestos como no bisiestos, y el cambio de año diciembre → enero).
* **Avisos personalizables por persona:** mismo día (`0`), día anterior (`1`) y/o semana anterior (`7`).
* **Tolerante a PC apagada:** usa un timer de `systemd --user` con `Persistent=true` y detección de cumpleaños pendientes si la PC estuvo apagada ese día.
* **Seguro por diseño:** sanitización de entradas, escape HTML en Telegram, permisos `0600` en credenciales locales y filtrado opcional por email verificado (`allowed_email`).

---

## Arquitectura rápida

```text
[Celular: Google Form] ──► [Google Sheet (CSV)] ──► [cumplidora.py + systemd timer] ──► [Push a Telegram]
```

---

## Puesta en marcha (5 minutos)

### Paso 1: Crear tu Bot de Telegram (1 min)
1. En Telegram buscá a **`@BotFather`** y enviá `/newbot`.
2. Elegí un nombre y un usuario terminado en `bot`.
3. Copiá el **Token** que te devuelve, entrá al chat de tu nuevo bot y tocá **Iniciar** (o mandale `Hola`).

### Paso 2: Crear el Formulario de Google + Planilla en 1 clic (2 min)
Podés usar el generador automático incluido en [`google_form_creator.gs`](./google_form_creator.gs):
1. Abrí [script.google.com](https://script.google.com) → **Nuevo proyecto**.
2. Pegá el contenido de `google_form_creator.gs` y tocá **Ejecutar**.
3. En el registro inferior vas a obtener **2 links**:
   * 📱 **Link del Formulario:** abrilo en Chrome de tu celular → menú `⋮` → **"Agregar a la pantalla principal"**.
   * 📊 **Link de la Planilla (Google Sheets):** abrilo en la PC → **Archivo → Compartir → Publicar en la web** → elegí **"Valores separados por comas (.csv)"** → **Publicar** y copiá ese enlace.
4. *(Opcional)* Una vez creado el formulario, ya podés borrar el proyecto en `script.google.com`.

### Paso 3: Vincular todo en tu PC (1 min)
Ejecutá el asistente interactivo:

```bash
python3 cumplidora.py setup
```

El asistente te pedirá tu Token de bot de Telegram y la URL del Google Sheets. Una vez enviaste el /start del bot en Telegram, apreta enter y se detecta automáticamente tu `chat_id` de Telegram, te envía un mensaje de bienvenida, guarda `config.json` y activa el timer de `systemd --user`.

---

## Uso cotidiano

La aplicación checkea 2 veces al día (A las 9hs y a las 18hs) si hay que recordar de algún cumpleaños. Si la pc está apagada en ese horario, la próxima vez que se prenda, ejecutará el script para checkear si hay que hacer algún recordatorio.

Agregá, modificá o borrá cumpleaños a través del Google Forms y estate atento a las notificaciones de telegram para disfrutar de tu recordatorio de cumpleaños.

## Comandos disponibles

```bash
# Listar todos los cumpleaños ordenados por cercanía
python3 cumplidora.py list

# Forzar sincronización inmediata con Google Sheets
python3 cumplidora.py sync

# Ejecutar el chequeo de hoy y enviar avisos pendientes
python3 cumplidora.py check

# Simular avisos sin enviar mensajes ni modificar estado
python3 cumplidora.py check --dry-run
python3 cumplidora.py check --dry-run --date 2026-12-28

# Enviar un mensaje de prueba a Telegram
python3 cumplidora.py test-telegram

# Agregar o eliminar cumpleaños locales desde la terminal
python3 cumplidora.py add "Juan Pérez" 15/04 --notify 0,1,7 --notes "Amigo facu"
python3 cumplidora.py remove "Juan Pérez"

# Estado y logs del timer automático en systemd
systemctl --user list-timers cumplidora.timer
journalctl --user -u cumplidora.service -n 30
```

## Edición, baja y seguridad opcional
* **Editar un cumpleaños desde el celular:** volvé a enviar el formulario con el **mismo nombre**; prevalece la fila más reciente.
* **Eliminar un cumpleaños:** enviá el formulario con ese nombre y escribí `BORRAR` en **Notas** (o eliminá la fila en Google Sheets).
* **Restringir envíos a tu cuenta de Google (opcional):** en Google Forms activá *Configuración → Respuestas → Recopilar direcciones de correo electrónico (Verificadas)* y agregá tu correo en `"allowed_email":"tu_email@example.com"` dentro de `config.json`.

## Tests

```bash
PYTHONPATH=. python3 -m unittest discover -s tests -v
```

## Licencia

Distribuido bajo la licencia [MIT](./LICENSE).
