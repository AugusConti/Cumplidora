#Cumplidora

🇪🇸 [Leer en Español](./README.es.md)

Lightweight, zero-dependency birthday reminder service for Linux that lets you add birthdays on the go from your phone via **Google Forms + Google Sheets** (even while your PC is powered off) and delivers push notifications through a **Telegram Bot**.

* **Zero external dependencies:** built strictly on the Python 3 standard library.
* **Year-agnostic birthdays:** tracks day and month only, properly handling `Feb 29` across leap and non-leap years as well as December → January wrap-around.
* **Per-person reminder schedules:** notify on the birthday itself (`0`), the day before (`1`), and/or a week in advance (`7`).
* **Offline-PC resilient:** scheduled via a `systemd --user` timer (`Persistent=true`) with automatic network retries on boot and belated catch-up alerts if your machine was off on someone's birthday.
* **Safe by design:** input sanitization, HTML escaping for Telegram payloads, `0600` local credential permissions, HTTPS-only transport with response size caps, and optional verified-sender filtering (`allowed_email`).

---

## Architecture

```text
[Phone: Google Form] ──► [Google Sheet (CSV)] ──► [cumplidora.py + systemd timer] ──► [Telegram Push]
```

---

## Quick Start (5 minutes)

### 1. Create a Telegram Bot (1 min)
1. Message **`@BotFather`** on Telegram and send `/newbot`.
2. Pick a display name and a `bot`-suffixed username.
3. Copy the **API Token**, open a chat with your new bot, and tap **Start** (or send `Hello`).

### 2. Generate the Google Form + Linked Sheet in 1 click (2 min)
Use the included Apps Script generator in [`google_form_creator.gs`](./google_form_creator.gs):
1. Open [script.google.com](https://script.google.com) → **New project**.
2. Paste the contents of `google_form_creator.gs` and click **Run**.
3. The execution log will output **2 links**:
   * 📱 **Form URL:** open it in mobile Chrome → menu `⋮` → **"Add to Home screen"** for quick access anywhere.
   * 📊 **Google Sheet URL:** open it → **File → Share → Publish to web** → choose **"Comma-separated values (.csv)"** → **Publish**, and copy that URL.
4. *(Optional)* Once generated, you can delete the Apps Script project from `script.google.com`.

### 3. Run the Interactive Setup on Linux (1 min)

```bash
python3 cumplidora.py setup
```

The wizard will ask you the Telegram bot Token and the Google Sheets URL. Once done, it automatically detects your Telegram `chat_id`, sends a test notification to your phone, writes `config.json`, and installs/enables the `systemd --user` timer.

---

## CLI Reference

```bash
# List all registered birthdays sorted by days remaining
python3 cumplidora.py list

# Force an immediate sync from Google Sheets
python3 cumplidora.py sync

# Run today's check and send due notifications
python3 cumplidora.py check

# Preview notifications without sending messages or updating state
python3 cumplidora.py check --dry-run
python3 cumplidora.py check --dry-run --date 2026-12-28

# Send a test message to Telegram
python3 cumplidora.py test-telegram

# Add or remove local birthdays directly from the terminal
python3 cumplidora.py add "John Doe" 15/04 --notify 0,1,7 --notes "Gift idea: book"
python3 cumplidora.py remove "John Doe"

# Inspect systemd timer schedule and service logs
systemctl --user list-timers cumplidora.timer
journalctl --user -u cumplidora.service -n 30
```

## Updating, Deleting & Optional Hardening
* **Update an entry from your phone:** submit the form again with the **same name**; the latest row overrides previous ones.
* **Delete an entry:** submit the form with that name and `BORRAR` (or `DELETE`) in **Notes**, or delete the row directly in Google Sheets.
* **Restrict form submissions to your Google account (optional):** in Google Forms enable *Settings → Responses → Collect email addresses (Verified)*, and set `"allowed_email":"your_email@example.com"` in `config.json`.

## Running Tests

```bash
PYTHONPATH=. python3 -m unittest discover -s tests -v
```

## License

Released under the [MIT License](./LICENSE).
