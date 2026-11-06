#!/usr/bin/env python3
"""
Cumplidora - Recordatorio de cumpleaños con sincronización desde Google Forms/Sheets
y notificaciones push por Telegram.

100% biblioteca estándar de Python (sin dependencias externas).
"""

from __future__ import annotations

import argparse
import calendar
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
import html
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import csv

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = BASE_DIR / "config.json"
DATA_DIR = BASE_DIR / "data"
SHEET_CACHE_PATH = DATA_DIR / "sheet_cache.json"
LOCAL_BIRTHDAYS_PATH = DATA_DIR / "local_birthdays.json"
STATE_PATH = DATA_DIR / "state.json"

MONTH_ALIASES: dict[str, int] = {
    "ene": 1,
    "enero": 1,
    "jan": 1,
    "january": 1,
    "feb": 2,
    "febrero": 2,
    "february": 2,
    "mar": 3,
    "marzo": 3,
    "march": 3,
    "abr": 4,
    "abril": 4,
    "apr": 4,
    "april": 4,
    "may": 5,
    "mayo": 5,
    "jun": 6,
    "junio": 6,
    "june": 6,
    "jul": 7,
    "julio": 7,
    "july": 7,
    "ago": 8,
    "agosto": 8,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "set": 9,
    "sept": 9,
    "septiembre": 9,
    "setiembre": 9,
    "september": 9,
    "oct": 10,
    "octubre": 10,
    "october": 10,
    "nov": 11,
    "noviembre": 11,
    "november": 11,
    "dic": 12,
    "diciembre": 12,
    "dec": 12,
    "december": 12,
}

MONTH_NAMES_ES = [
    "",
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]


@dataclass
class BirthdayEntry:
    name: str
    day: int
    month: int
    notify_days: list[int] = field(default_factory=lambda: [0, 1, 7])
    notes: str = ""
    source: str = "sheet"

    @property
    def key(self) -> str:
        return normalize_text(self.name)

    @property
    def formatted_day_month(self) -> str:
        return f"{self.day:02d}/{self.month:02d}"


@dataclass
class NotificationItem:
    entry: BirthdayEntry
    target_date: date
    days_until: int  # >= 0 para hoy/futuro, < 0 para aviso atrasado (catch-up)
    event_key: str
    is_catchup: bool = False


def strip_control_chars(text: str, max_len: int = 300) -> str:
    """Elimina caracteres de control (ej. secuencias ANSI de terminal) y limita longitud."""
    cleaned = "".join(ch for ch in text if ch.isprintable() or ch == " ")
    return cleaned.strip()[:max_len]


def strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def normalize_text(text: str) -> str:
    cleaned = strip_accents(text).casefold().strip()
    return re.sub(r"\s+", " ", cleaned)


def validate_day_month(day: int, month: int) -> None:
    if not 1 <= month <= 12:
        raise ValueError(f"Mes inválido: {month} (debe estar entre 1 y 12)")
    # Usamos 2024 (año bisiesto) para permitir 29/02 y rechazar ej. 31/04 o 30/02
    max_day = calendar.monthrange(2024, month)[1]
    if not 1 <= day <= max_day:
        raise ValueError(
            f"Día inválido: {day:02d}/{month:02d} ({MONTH_NAMES_ES[month]} tiene hasta {max_day} días)"
        )


def parse_month(raw: str) -> int:
    text = normalize_text(raw)
    if not text:
        raise ValueError("Mes vacío")

    # Soporta formatos como "04 - Abril", "4", "04", "Abril", "abr."
    num_match = re.match(r"^(\d{1,2})\b", text)
    if num_match:
        month = int(num_match.group(1))
        if 1 <= month <= 12:
            return month
        raise ValueError(f"Mes numérico fuera de rango: {raw!r}")

    alpha_cleaned = re.sub(r"[^a-z]", "", text)
    if alpha_cleaned in MONTH_ALIASES:
        return MONTH_ALIASES[alpha_cleaned]

    raise ValueError(f"No se pudo interpretar el mes: {raw!r}")


def parse_date_fields(
    day_raw: str = "", month_raw: str = "", date_raw: str = ""
) -> tuple[int, int]:
    """Interpreta día y mes desde columnas separadas o una columna combinada."""
    if day_raw.strip() and month_raw.strip():
        day_match = re.search(r"\d{1,2}", day_raw.strip())
        if not day_match:
            raise ValueError(f"Día inválido: {day_raw!r}")
        day = int(day_match.group(0))
        month = parse_month(month_raw)
        validate_day_month(day, month)
        return day, month

    combined = date_raw.strip() or day_raw.strip()
    if not combined:
        raise ValueError("Falta la fecha de cumpleaños (día/mes)")

    # Formato ISO YYYY-MM-DD
    iso_match = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$", combined)
    if iso_match:
        month = int(iso_match.group(2))
        day = int(iso_match.group(3))
        validate_day_month(day, month)
        return day, month

    # Formato DD/MM o DD/MM/YYYY o DD-MM
    dmy_match = re.match(r"^(\d{1,2})[-/.](\d{1,2})(?:[-/.]\d{2,4})?$", combined)
    if dmy_match:
        day = int(dmy_match.group(1))
        month = int(dmy_match.group(2))
        validate_day_month(day, month)
        return day, month

    # Formato "15 de abril" o "15 abril"
    text_match = re.match(r"^(\d{1,2})\s*(?:de\s+)?([a-zA-ZáéíóúÁÉÍÓÚñÑ.]+)", combined)
    if text_match:
        day = int(text_match.group(1))
        month = parse_month(text_match.group(2))
        validate_day_month(day, month)
        return day, month

    raise ValueError(f"Formato de fecha no reconocido: {combined!r}")


def parse_notify_days(raw: str, default_days: list[int] | None = None) -> list[int]:
    """Convierte opciones de Google Forms o números en desplazamientos de días [0, 1, 7]."""
    fallback = sorted(set(default_days if default_days is not None else [0, 1, 7]))
    if not raw or not raw.strip():
        return fallback

    norm = normalize_text(raw)
    result: set[int] = set()

    for part in re.split(r"[,;/|]+", norm):
        token = part.strip()
        if not token:
            continue
        if token.isdigit():
            result.add(int(token))
            continue
        if any(p in token for p in ("mismo dia", "hoy", "en el dia", "ese dia")):
            result.add(0)
        if any(p in token for p in ("dia anterior", "un dia antes", "1 dia antes", "ayer")):
            result.add(1)
        if any(
            p in token
            for p in ("semana anterior", "una semana antes", "1 semana antes", "7 dias antes")
        ):
            result.add(7)
        custom_days = re.search(r"(\d+)\s*dias?\s*antes", token)
        if custom_days:
            result.add(int(custom_days.group(1)))
        custom_weeks = re.search(r"(\d+)\s*semanas?\s*antes", token)
        if custom_weeks:
            result.add(int(custom_weeks.group(1)) * 7)

    return sorted(result) if result else fallback


def normalize_sheet_csv_url(url: str) -> str:
    """Normaliza links de Google Sheets a su URL directa de descarga CSV."""
    url = url.strip()
    if not url:
        return ""

    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)

    # Caso 1: URL publicada como /pubhtml -> pasar a /pub?output=csv
    if "/spreadsheets/d/e/" in parsed.path and parsed.path.endswith("/pubhtml"):
        new_path = parsed.path[: -len("/pubhtml")] + "/pub"
        new_query: dict[str, str] = {"output": "csv"}
        if "gid" in query:
            new_query["gid"] = query["gid"][0]
            new_query["single"] = "true"
        return urllib.parse.urlunparse(
            parsed._replace(path=new_path, query=urllib.parse.urlencode(new_query))
        )

    # Caso 2: URL normal de edición /spreadsheets/d/<ID>/edit
    edit_match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", parsed.path)
    if edit_match and "/d/e/" not in parsed.path and "export" not in parsed.path:
        sheet_id = edit_match.group(1)
        new_query = {"format": "csv"}
        if "gid" in query:
            new_query["gid"] = query["gid"][0]
        # Extraer gid si viene en el fragment (#gid=123)
        frag_match = re.search(r"gid=(\d+)", parsed.fragment)
        if "gid" not in new_query and frag_match:
            new_query["gid"] = frag_match.group(1)
        return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?{urllib.parse.urlencode(new_query)}"

    return url


def _detect_column_indices(headers: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    norm_headers = [normalize_text(h) for h in headers]

    for idx, h in enumerate(norm_headers):
        if not h or "marca temporal" in h or "timestamp" in h:
            continue
        if "email" not in mapping and any(
            k in h for k in ("direccion de correo", "correo electronico", "email")
        ):
            mapping["email"] = idx
        elif "name" not in mapping and any(
            k in h for k in ("nombre", "persona", "cumpleanero", "quien", "name")
        ):
            mapping["name"] = idx
        elif "day" not in mapping and (
            h in ("dia", "day") or h.startswith("dia ") or h.startswith("dia(")
        ):
            mapping["day"] = idx
        elif "month" not in mapping and (
            h in ("mes", "month") or h.startswith("mes ") or h.startswith("mes(")
        ):
            mapping["month"] = idx
        elif "date" not in mapping and any(
            k in h for k in ("fecha", "cumpleanos", "dia y mes", "date")
        ):
            mapping["date"] = idx
        elif "notify" not in mapping and any(
            k in h for k in ("aviso", "recordatorio", "notifica", "cuando")
        ):
            mapping["notify"] = idx
        elif "notes" not in mapping and any(
            k in h for k in ("nota", "observacion", "comentario", "detalle", "accion")
        ):
            mapping["notes"] = idx

    return mapping


def parse_csv_content(
    csv_text: str,
    default_notify_days: list[int] | None = None,
    allowed_email: str = "",
) -> tuple[list[BirthdayEntry], list[str]]:
    """
    Parsea el CSV exportado por Google Sheets.
    - Si una misma persona se carga más de una vez, prevalece la fila más reciente.
    - Si en Notas se escribe 'BORRAR' o 'ELIMINAR', se da de baja a esa persona.
    - Si allowed_email está configurado y el formulario recopila emails, ignora otros remitentes.
    """
    warnings: list[str] = []
    clean_text = csv_text.lstrip("\ufeff")
    reader = csv.reader(io.StringIO(clean_text))
    rows = list(reader)
    if not rows:
        return [], warnings

    headers = rows[0]
    col_map = _detect_column_indices(headers)
    if "name" not in col_map:
        raise ValueError(
            f"No se encontró una columna de 'Nombre' en el CSV. Encabezados detectados: {headers}"
        )
    if "date" not in col_map and not ("day" in col_map and "month" in col_map):
        raise ValueError(
            "No se encontraron columnas de 'Día'/'Mes' ni 'Fecha' en el CSV. "
            f"Encabezados detectados: {headers}"
        )

    expected_email = allowed_email.strip().casefold()
    by_key: dict[str, BirthdayEntry] = {}

    for row_num, row in enumerate(rows[1:], start=2):
        if not any(cell.strip() for cell in row):
            continue

        def get_col(field_name: str) -> str:
            idx = col_map.get(field_name)
            if idx is None or idx >= len(row):
                return ""
            return row[idx].strip()

        if expected_email and "email" in col_map:
            row_email = get_col("email").casefold()
            if row_email != expected_email:
                warnings.append(f"Fila {row_num}: ignorada por email no autorizado ({row_email!r})")
                continue

        name = strip_control_chars(get_col("name"), max_len=120)
        if not name:
            continue

        notes = strip_control_chars(get_col("notes"), max_len=300)
        if normalize_text(notes) in ("borrar", "eliminar", "baja", "delete"):
            by_key.pop(normalize_text(name), None)
            continue

        try:
            day, month = parse_date_fields(
                day_raw=get_col("day"),
                month_raw=get_col("month"),
                date_raw=get_col("date"),
            )
        except ValueError as exc:
            warnings.append(f"Fila {row_num} ({name}): {exc}")
            continue

        notify_days = parse_notify_days(get_col("notify"), default_notify_days)
        entry = BirthdayEntry(
            name=name,
            day=day,
            month=month,
            notify_days=notify_days,
            notes=notes,
            source="sheet",
        )
        by_key[entry.key] = entry

    return list(by_key.values()), warnings


def resolve_birthday_in_year(year: int, month: int, day: int) -> date:
    """Resuelve la fecha de cumpleaños en un año dado (29/02 -> 28/02 en años no bisiestos)."""
    if month == 2 and day == 29 and not calendar.isleap(year):
        return date(year, 2, 28)
    return date(year, month, day)


def next_birthday_date(today: date, month: int, day: int) -> date:
    candidate = resolve_birthday_in_year(today.year, month, day)
    if candidate >= today:
        return candidate
    return resolve_birthday_in_year(today.year + 1, month, day)


def previous_birthday_date(today: date, month: int, day: int) -> date:
    candidate = resolve_birthday_in_year(today.year, month, day)
    if candidate < today:
        return candidate
    return resolve_birthday_in_year(today.year - 1, month, day)


def compute_due_notifications(
    entries: list[BirthdayEntry],
    today: date,
    sent_events: set[str],
    last_check_date: date | None = None,
    catchup_missed_days: int = 3,
) -> list[NotificationItem]:
    """Calcula qué notificaciones corresponde enviar en la fecha `today`."""
    due: list[NotificationItem] = []

    for entry in entries:
        # 1. Avisos de hoy o anticipados (ej. 0, 1, 7 días antes)
        upcoming = next_birthday_date(today, entry.month, entry.day)
        days_until = (upcoming - today).days

        if days_until in entry.notify_days:
            event_key = f"{entry.key}:{upcoming.year}:offset_{days_until}"
            if event_key not in sent_events:
                due.append(
                    NotificationItem(
                        entry=entry,
                        target_date=upcoming,
                        days_until=days_until,
                        event_key=event_key,
                        is_catchup=False,
                    )
                )

        # 2. Aviso atrasado (si la PC estuvo apagada el día exacto del cumpleaños)
        if catchup_missed_days > 0 and 0 in entry.notify_days and last_check_date is not None:
            prev_bday = previous_birthday_date(today, entry.month, entry.day)
            days_since = (today - prev_bday).days
            if 1 <= days_since <= catchup_missed_days and prev_bday > last_check_date:
                same_day_key = f"{entry.key}:{prev_bday.year}:offset_0"
                catchup_key = f"{entry.key}:{prev_bday.year}:catchup"
                if same_day_key not in sent_events and catchup_key not in sent_events:
                    due.append(
                        NotificationItem(
                            entry=entry,
                            target_date=prev_bday,
                            days_until=-days_since,
                            event_key=catchup_key,
                            is_catchup=True,
                        )
                    )

    # Ordenar: primero cumpleaños de hoy, luego atrasados, luego los más próximos
    due.sort(key=lambda item: (0 if item.days_until == 0 else 1, abs(item.days_until), item.entry.name.lower()))
    return due


def format_notification_message(items: list[NotificationItem]) -> str:
    lines: list[str] = ["🎉 <b>Recordatorio de Cumpleaños (Cumplidora)</b>", ""]

    for item in items:
        entry = item.entry
        safe_name = html.escape(entry.name)
        date_label = f"{item.target_date.day:02d}/{item.target_date.month:02d}"
        leap_note = (
            " <i>(nacido/a el 29/02)</i>"
            if (entry.month == 2 and entry.day == 29 and item.target_date.day == 28)
            else ""
        )

        if item.is_catchup:
            days_ago = abs(item.days_until)
            when_str = "ayer" if days_ago == 1 else f"hace {days_ago} días"
            line = f"⏳ <b>Aviso pendiente:</b> {when_str} ({date_label}) fue el cumpleaños de <b>{safe_name}</b>{leap_note}."
        elif item.days_until == 0:
            line = f"🎂 <b>¡HOY ({date_label}) es el cumpleaños de {safe_name}!</b>{leap_note}"
        elif item.days_until == 1:
            line = f"🎈 <b>Mañana ({date_label})</b> cumple años <b>{safe_name}</b>{leap_note}."
        elif item.days_until == 7:
            line = f"📅 <b>En una semana ({date_label})</b> cumple años <b>{safe_name}</b>{leap_note}."
        else:
            line = f"🔔 <b>En {item.days_until} días ({date_label})</b> cumple años <b>{safe_name}</b>{leap_note}."

        if entry.notes:
            line += f"\n   📝 <i>{html.escape(entry.notes)}</i>"
        lines.append(line)

    return "\n".join(lines)


MAX_HTTP_BYTES = 2 * 1024 * 1024  # Límite defensivo de 2 MB para respuestas HTTP


def http_get_text(url: str, timeout: int = 15, retries: int = 3, retry_delay: float = 5.0) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"Por seguridad solo se permiten URLs https:// (recibido: {parsed.scheme!r})")

    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Cumplidora/1.0 (+linux-birthday-notifier)"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw_bytes = resp.read(MAX_HTTP_BYTES + 1)
                if len(raw_bytes) > MAX_HTTP_BYTES:
                    raise ValueError("La respuesta excede el tamaño máximo permitido (2 MB)")
                charset = resp.headers.get_content_charset() or "utf-8"
                return raw_bytes.decode(charset, errors="replace")
        except urllib.error.HTTPError as exc:
            last_exc = exc
            # Solo reintentar errores transitorios del servidor (5xx o 429)
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(retry_delay)
            else:
                raise
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(retry_delay)
    assert last_exc is not None
    raise last_exc


def send_telegram_message(
    bot_token: str,
    chat_id: str,
    text: str,
    retries: int = 3,
    retry_delay: float = 5.0,
) -> None:
    # Telegram permite hasta 4096 caracteres por mensaje
    if len(text) > 4000:
        text = text[:3950].rsplit("\n", 1)[0] + "\n\n<i>(...mensaje truncado por longitud)</i>"

    api_url = f"https://api.telegram.org/bot{bot_token.strip()}/sendMessage"
    payload = json.dumps(
        {
            "chat_id": str(chat_id).strip(),
            "text": text,
            "parse_mode": "HTML",
        }
    ).encode("utf-8")

    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                api_url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = json.loads(resp.read(MAX_HTTP_BYTES).decode("utf-8"))
                if not body.get("ok"):
                    raise RuntimeError(f"Respuesta de Telegram no OK: {body}")
                return
        except urllib.error.HTTPError as exc:
            last_exc = exc
            # Solo reintentar errores transitorios del servidor (5xx o 429)
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(retry_delay)
            else:
                raise
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(retry_delay)
    assert last_exc is not None
    raise last_exc


def detect_telegram_chat_id(bot_token: str) -> tuple[str, str] | None:
    """Consulta getUpdates para detectar automáticamente el chat_id del usuario."""
    api_url = f"https://api.telegram.org/bot{bot_token.strip()}/getUpdates"
    raw = http_get_text(api_url, timeout=15, retries=2, retry_delay=2.0)
    data = json.loads(raw)
    if not data.get("ok") or not data.get("result"):
        return None
    for update in reversed(data["result"]):
        msg = update.get("message") or update.get("edited_message") or {}
        chat = msg.get("chat") or {}
        if "id" in chat:
            name = chat.get("first_name") or chat.get("username") or "Usuario"
            return str(chat["id"]), name
    return None


def load_json_file(path: Path, default: object) -> object:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save_json_file(path: Path, data: object, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    if private:
        os.chmod(tmp_path, 0o600)
    tmp_path.replace(path)


def entries_from_dicts(raw_list: list[dict]) -> list[BirthdayEntry]:
    result: list[BirthdayEntry] = []
    for item in raw_list:
        result.append(
            BirthdayEntry(
                name=item["name"],
                day=int(item["day"]),
                month=int(item["month"]),
                notify_days=[int(x) for x in item.get("notify_days", [0, 1, 7])],
                notes=item.get("notes", ""),
                source=item.get("source", "local"),
            )
        )
    return result


def load_config(config_path: Path) -> dict:
    if not config_path.exists():
        raise FileNotFoundError(
            f"No existe el archivo de configuración {config_path}.\n"
            f"Ejecutá: python3 {Path(__file__).name} setup"
        )
    data = load_json_file(config_path, {})
    assert isinstance(data, dict)
    return data


def sync_and_load_entries(config: dict, allow_cached_fallback: bool = True) -> list[BirthdayEntry]:
    default_days = [int(d) for d in config.get("default_notify_days", [0, 1, 7])]
    allowed_email = str(config.get("allowed_email", "")).strip()
    raw_url = str(config.get("google_sheet_csv_url", "")).strip()
    sheet_entries: list[BirthdayEntry] = []

    if raw_url and not raw_url.startswith("PEGAR_") and "/.../" not in raw_url:
        csv_url = normalize_sheet_csv_url(raw_url)
        try:
            csv_text = http_get_text(csv_url, timeout=15, retries=3, retry_delay=5.0)
            sheet_entries, warnings = parse_csv_content(
                csv_text, default_days, allowed_email=allowed_email
            )
            for w in warnings:
                print(f"[AVISO CSV] {w}", file=sys.stderr)
            save_json_file(SHEET_CACHE_PATH, [asdict(e) for e in sheet_entries])
        except Exception as exc:
            if allow_cached_fallback and SHEET_CACHE_PATH.exists():
                print(
                    f"[AVISO] No se pudo descargar Google Sheet ({exc}); usando caché local.",
                    file=sys.stderr,
                )
                cached = load_json_file(SHEET_CACHE_PATH, [])
                assert isinstance(cached, list)
                sheet_entries = entries_from_dicts(cached)
            else:
                raise

    local_raw = load_json_file(LOCAL_BIRTHDAYS_PATH, [])
    assert isinstance(local_raw, list)
    local_entries = entries_from_dicts(local_raw)

    merged: dict[str, BirthdayEntry] = {}
    for entry in sheet_entries:
        merged[entry.key] = entry
    for entry in local_entries:
        merged[entry.key] = entry

    return list(merged.values())


def load_state() -> tuple[set[str], date | None]:
    raw = load_json_file(STATE_PATH, {})
    assert isinstance(raw, dict)
    sent = set(raw.get("sent_events", []))
    last_check_str = raw.get("last_check_date")
    last_check = date.fromisoformat(last_check_str) if last_check_str else None
    return sent, last_check


def save_state(sent_events: set[str], check_date: date) -> None:
    # Podar eventos de años viejos (anteriores a check_date.year - 1) para que no crezca indefinidamente
    min_year = check_date.year - 1
    kept: list[str] = []
    for ev in sorted(sent_events):
        parts = ev.split(":")
        if len(parts) >= 3 and parts[1].isdigit() and int(parts[1]) < min_year:
            continue
        kept.append(ev)
    save_json_file(
        STATE_PATH,
        {
            "last_check_date": check_date.isoformat(),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "sent_events": kept,
        },
    )


def cmd_check(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    today = date.fromisoformat(args.date) if args.date else date.today()
    entries = sync_and_load_entries(config, allow_cached_fallback=bool(args.dry_run))
    sent_events, last_check_date = load_state()
    catchup_days = int(config.get("catchup_missed_days", 3))

    due = compute_due_notifications(
        entries=entries,
        today=today,
        sent_events=sent_events,
        last_check_date=last_check_date,
        catchup_missed_days=catchup_days,
    )

    if not due:
        print(f"[{today.isoformat()}] {len(entries)} cumpleaños revisados. Sin avisos pendientes para hoy.")
        if not args.dry_run:
            effective_last = max(last_check_date, today) if last_check_date else today
            save_state(sent_events, effective_last)
        return 0

    message = format_notification_message(due)
    print(message)

    if args.dry_run:
        print("\n(Modo --dry-run: no se envió mensaje por Telegram ni se modificó el estado.)")
        return 0

    bot_token = str(config.get("telegram_bot_token", "")).strip()
    chat_id = str(config.get("telegram_chat_id", "")).strip()
    if not bot_token or bot_token.startswith("PEGAR_") or not chat_id or chat_id.startswith("PEGAR_"):
        raise RuntimeError(
            "Faltan telegram_bot_token o telegram_chat_id en config.json. Ejecutá: python3 cumplidora.py setup"
        )

    send_telegram_message(bot_token, chat_id, message)
    for item in due:
        sent_events.add(item.event_key)
    effective_last = max(last_check_date, today) if last_check_date else today
    save_state(sent_events, effective_last)
    print(f"\n✅ Se enviaron {len(due)} recordatorio(s) por Telegram.")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    config = load_config(args.config) if args.config.exists() else {}
    entries = sync_and_load_entries(config, allow_cached_fallback=True)
    if not entries:
        print("Todavía no hay cumpleaños cargados.")
        return 0

    today = date.today()
    rows = []
    for e in entries:
        nxt = next_birthday_date(today, e.month, e.day)
        days_left = (nxt - today).days
        rows.append((days_left, nxt, e))

    rows.sort(key=lambda r: (r[0], r[2].name.lower()))
    print(f"🎂 Cumpleaños registrados ({len(rows)}):\n")
    for days_left, _nxt, e in rows:
        when = "¡HOY!" if days_left == 0 else ("mañana" if days_left == 1 else f"en {days_left} días")
        avisos = ", ".join(f"{d}d" for d in e.notify_days)
        note_str = f" | Nota: {e.notes}" if e.notes else ""
        print(f"  • {e.formatted_day_month} - {e.name:<24} ({when:<12}) [avisos: {avisos}]{note_str}")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    day, month = parse_date_fields(date_raw=args.fecha)
    notify_days = parse_notify_days(args.notify, [0, 1, 7])
    local_raw = load_json_file(LOCAL_BIRTHDAYS_PATH, [])
    assert isinstance(local_raw, list)
    entries = entries_from_dicts(local_raw)

    new_entry = BirthdayEntry(
        name=args.nombre.strip(),
        day=day,
        month=month,
        notify_days=notify_days,
        notes=args.notes.strip(),
        source="local",
    )
    by_key = {e.key: e for e in entries}
    by_key[new_entry.key] = new_entry
    save_json_file(LOCAL_BIRTHDAYS_PATH, [asdict(e) for e in by_key.values()])
    print(f"✅ Guardado localmente: {new_entry.name} ({new_entry.formatted_day_month}) - avisos: {notify_days}")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    local_raw = load_json_file(LOCAL_BIRTHDAYS_PATH, [])
    assert isinstance(local_raw, list)
    entries = entries_from_dicts(local_raw)
    target = normalize_text(args.nombre)
    remaining = [e for e in entries if e.key != target]
    if len(remaining) == len(entries):
        print(f"No se encontró '{args.nombre}' en la lista local (si viene de Google Sheets, borralo en la planilla o agregá una fila con nota BORRAR).")
        return 1
    save_json_file(LOCAL_BIRTHDAYS_PATH, [asdict(e) for e in remaining])
    print(f"🗑️ Eliminado localmente: {args.nombre}")
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    entries = sync_and_load_entries(config, allow_cached_fallback=False)
    print(f"✅ Sincronización exitosa. Total de cumpleaños activos: {len(entries)}")
    return 0


def cmd_test_telegram(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    bot_token = str(config.get("telegram_bot_token", "")).strip()
    chat_id = str(config.get("telegram_chat_id", "")).strip()
    send_telegram_message(
        bot_token,
        chat_id,
        "🎂 <b>¡Prueba exitosa de Cumplidora!</b>\nLas notificaciones de cumpleaños están funcionando correctamente en tu PC.",
    )
    print("✅ Mensaje de prueba enviado a tu Telegram.")
    return 0


def install_systemd_timer() -> None:
    user_systemd_dir = Path.home() / ".config" / "systemd" / "user"
    user_systemd_dir.mkdir(parents=True, exist_ok=True)

    src_service = BASE_DIR / "systemd" / "cumplidora.service"
    src_timer = BASE_DIR / "systemd" / "cumplidora.timer"

    service_content = src_service.read_text(encoding="utf-8").replace(
        "{{CUMPLIDORA_SCRIPT}}", str(BASE_DIR / "cumplidora.py")
    )
    (user_systemd_dir / "cumplidora.service").write_text(service_content, encoding="utf-8")
    (user_systemd_dir / "cumplidora.timer").write_text(
        src_timer.read_text(encoding="utf-8"), encoding="utf-8"
    )

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", "cumplidora.timer"], check=True)
    print("✅ Timer diario instalado y activado en systemd (--user).")


def cmd_install_timer(_args: argparse.Namespace) -> int:
    install_systemd_timer()
    return 0


def cmd_setup(args: argparse.Namespace) -> int:
    print("=== Configuración interactiva de Cumplidora ===\n")
    existing: dict = {}
    if args.config.exists():
        loaded = load_json_file(args.config, {})
        if isinstance(loaded, dict):
            existing = loaded

    cur_token = str(existing.get("telegram_bot_token", ""))
    prompt_token = f"1) Pegá el Token de tu Bot de Telegram [{cur_token[:10]}...]: " if cur_token else "1) Pegá el Token de tu Bot de Telegram (de @BotFather): "
    bot_token = input(prompt_token).strip() or cur_token
    if not bot_token:
        print("Se requiere el token del bot para continuar.")
        return 1

    chat_id = str(existing.get("telegram_chat_id", "")).strip()
    print("\n   Ahora abrí tu bot en Telegram desde el celu, tocá 'Iniciar' (o mandale 'Hola')")
    input("   y presioná ENTER acá para detectar tu Chat ID automáticamente... ")

    detected = detect_telegram_chat_id(bot_token)
    if detected:
        chat_id, user_name = detected
        print(f"   ✅ Detectado chat con {user_name} (chat_id: {chat_id})")
    else:
        chat_id = input(f"   No se detectaron mensajes recientes. Ingresá tu chat_id manualmente [{chat_id}]: ").strip() or chat_id

    if chat_id:
        send_telegram_message(
            bot_token,
            chat_id,
            "🎉 <b>¡Cumplidora vinculada con éxito!</b>\nAcá vas a recibir los avisos de cumpleaños.",
        )
        print("   📲 ¡Te acabamos de mandar un mensaje de bienvenida a Telegram!")

    cur_url = str(existing.get("google_sheet_csv_url", ""))
    print("\n2) Pegá el link CSV publicado de tu Google Sheet (o dejalo vacío por ahora):")
    sheet_url = input(f"   URL [{cur_url[:40] + '...' if cur_url else 'vacío'}]: ").strip() or cur_url

    config_data = {
        "telegram_bot_token": bot_token,
        "telegram_chat_id": chat_id,
        "google_sheet_csv_url": normalize_sheet_csv_url(sheet_url) if sheet_url else "",
        "allowed_email": existing.get("allowed_email", ""),
        "default_notify_days": existing.get("default_notify_days", [0, 1, 7]),
        "catchup_missed_days": existing.get("catchup_missed_days", 3),
    }
    save_json_file(args.config, config_data, private=True)
    print(f"\n✅ Configuración guardada en {args.config}")

    ans = input("\n3) ¿Querés activar ahora el chequeo automático diario al prender la PC (systemd timer)? [S/n]: ").strip().lower()
    if ans in ("", "s", "si", "sí", "y", "yes"):
        install_systemd_timer()

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Cumplidora: recordatorios de cumpleaños sincronizados con Google Forms/Sheets + Telegram."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Ruta al archivo config.json",
    )

    sub = parser.add_subparsers(dest="command")

    p_check = sub.add_parser("check", help="Sincroniza y envía las notificaciones pendientes de hoy")
    p_check.add_argument("--dry-run", action="store_true", help="Simula sin enviar a Telegram ni guardar estado")
    p_check.add_argument("--date", help="Simular otra fecha en formato YYYY-MM-DD")
    p_check.set_defaults(func=cmd_check)

    p_list = sub.add_parser("list", help="Lista todos los cumpleaños ordenados por cercanía")
    p_list.set_defaults(func=cmd_list)

    p_add = sub.add_parser("add", help="Agrega un cumpleaños localmente desde la terminal")
    p_add.add_argument("nombre", help="Nombre de la persona")
    p_add.add_argument("fecha", help="Día y mes (ej. 15/04)")
    p_add.add_argument("--notify", default="0,1,7", help="Días de anticipación separados por coma (default: 0,1,7)")
    p_add.add_argument("--notes", default="", help="Nota opcional")
    p_add.set_defaults(func=cmd_add)

    p_rm = sub.add_parser("remove", help="Elimina un cumpleaños guardado localmente")
    p_rm.add_argument("nombre", help="Nombre de la persona")
    p_rm.set_defaults(func=cmd_remove)

    p_sync = sub.add_parser("sync", help="Descarga y actualiza la caché desde Google Sheets")
    p_sync.set_defaults(func=cmd_sync)

    p_test = sub.add_parser("test-telegram", help="Envía un mensaje de prueba a tu Telegram")
    p_test.set_defaults(func=cmd_test_telegram)

    p_timer = sub.add_parser("install-timer", help="Instala y habilita el timer diario en systemd --user")
    p_timer.set_defaults(func=cmd_install_timer)

    p_setup = sub.add_parser("setup", help="Asistente interactivo de configuración inicial")
    p_setup.set_defaults(func=cmd_setup)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        # Si se ejecuta sin subcomando, corre `check` por defecto
        args.dry_run = False
        args.date = None
        return cmd_check(args)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
