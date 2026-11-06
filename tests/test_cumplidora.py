from datetime import date
import unittest

import cumplidora as c


class CumplidoraTests(unittest.TestCase):
    def test_parse_google_form_csv_and_overrides(self) -> None:
        csv_text = (
            "Marca temporal,Nombre,Día,Mes,Avisos,Notas\n"
            '06/11/2026 10:00:00,Juan Pérez,15,04 - Abril,"El mismo día, La semana anterior",Amigo facu\n'
            "06/11/2026 10:05:00,Ana Gómez,29,02 - Febrero,,\n"
            "06/11/2026 10:10:00,juan perez,16,Abril,El día anterior,Fecha corregida\n"
            "06/11/2026 10:12:00,Carlos Borrado,10,05 - Mayo,,\n"
            "06/11/2026 10:15:00,Carlos Borrado,10,05 - Mayo,,BORRAR\n"
        )
        entries, warnings = c.parse_csv_content(csv_text, default_notify_days=[0, 1, 7])
        self.assertEqual(warnings, [])
        self.assertEqual(len(entries), 2)

        by_key = {e.key: e for e in entries}
        juan = by_key["juan perez"]
        self.assertEqual((juan.day, juan.month), (16, 4))
        self.assertEqual(juan.notify_days, [1])
        self.assertEqual(juan.notes, "Fecha corregida")

        ana = by_key["ana gomez"]
        self.assertEqual((ana.day, ana.month), (29, 2))
        self.assertEqual(ana.notify_days, [0, 1, 7])

    def test_invalid_dates_rejected_with_warning(self) -> None:
        csv_text = (
            "Marca temporal,Nombre,Día,Mes,Avisos\n"
            "06/11/2026 10:00:00,Invalido Abril,31,04 - Abril,\n"
            "06/11/2026 10:01:00,Valido Mayo,31,05 - Mayo,\n"
        )
        entries, warnings = c.parse_csv_content(csv_text)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].name, "Valido Mayo")
        self.assertEqual(len(warnings), 1)

    def test_year_wraparound_december_to_january(self) -> None:
        entries = [c.BirthdayEntry(name="Sofía", day=4, month=1, notify_days=[0, 1, 7])]
        due = c.compute_due_notifications(
            entries=entries,
            today=date(2026, 12, 28),
            sent_events=set(),
        )
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0].days_until, 7)
        self.assertEqual(due[0].target_date, date(2027, 1, 4))

    def test_leap_year_feb_29_handling(self) -> None:
        entries = [c.BirthdayEntry(name="Bisiesto", day=29, month=2, notify_days=[0, 1])]

        # En 2026 (no bisiesto), se notifica el 28/02 (y el 27/02 como día anterior)
        due_non_leap = c.compute_due_notifications(entries, date(2026, 2, 27), set())
        self.assertEqual(len(due_non_leap), 1)
        self.assertEqual(due_non_leap[0].days_until, 1)
        self.assertEqual(due_non_leap[0].target_date, date(2026, 2, 28))

        # En 2028 (bisiesto), el 28/02 es 1 día antes del 29/02
        due_leap = c.compute_due_notifications(entries, date(2028, 2, 28), set())
        self.assertEqual(len(due_leap), 1)
        self.assertEqual(due_leap[0].days_until, 1)
        self.assertEqual(due_leap[0].target_date, date(2028, 2, 29))

    def test_deduplication_and_catchup_when_pc_was_off(self) -> None:
        entries = [c.BirthdayEntry(name="Martín", day=5, month=11, notify_days=[0, 1, 7])]

        # PC apagada desde el 03/11 hasta el 06/11 -> el cumple del 05/11 se detecta como pendiente
        due = c.compute_due_notifications(
            entries=entries,
            today=date(2026, 11, 6),
            sent_events=set(),
            last_check_date=date(2026, 11, 3),
            catchup_missed_days=3,
        )
        self.assertEqual(len(due), 1)
        self.assertTrue(due[0].is_catchup)
        self.assertEqual(due[0].days_until, -1)

        # Si ya fue enviado (o si ya se había enviado offset_0 ese día), no duplica
        sent = {due[0].event_key}
        due_again = c.compute_due_notifications(
            entries=entries,
            today=date(2026, 11, 6),
            sent_events=sent,
            last_check_date=date(2026, 11, 3),
            catchup_missed_days=3,
        )
        self.assertEqual(due_again, [])

    def test_html_formatting_escapes_special_characters(self) -> None:
        entry = c.BirthdayEntry(
            name="Juan <Pérez> & Cía",
            day=6,
            month=11,
            notify_days=[0],
            notes="ig: @juan_perez <regalo>",
        )
        due = c.compute_due_notifications([entry], date(2026, 11, 6), set())
        msg = c.format_notification_message(due)
        self.assertIn("Juan &lt;Pérez&gt; &amp; Cía", msg)
        self.assertIn("@juan_perez &lt;regalo&gt;", msg)

    def test_normalize_sheet_csv_url(self) -> None:
        pubhtml = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTest/pubhtml?gid=12345&single=true"
        self.assertEqual(
            c.normalize_sheet_csv_url(pubhtml),
            "https://docs.google.com/spreadsheets/d/e/2PACX-1vTest/pub?output=csv&gid=12345&single=true",
        )
        edit_url = "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOp/edit#gid=9876"
        self.assertEqual(
            c.normalize_sheet_csv_url(edit_url),
            "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOp/export?format=csv&gid=9876",
        )

    def test_security_strips_control_chars_and_filters_allowed_email(self) -> None:
        csv_text = (
            "Marca temporal,Dirección de correo electrónico,Nombre,Día,Mes,Notas\n"
            "06/11/2026 10:00:00,dueno@gmail.com,Ana\x1b[31m Roja,10,05,Nota\x07 limpia\n"
            "06/11/2026 10:05:00,intruso@evil.com,Ana Roja,10,05,BORRAR\n"
        )
        entries, warnings = c.parse_csv_content(csv_text, allowed_email="dueno@gmail.com")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].name, "Ana[31m Roja")
        self.assertNotIn("\x1b", entries[0].name)
        self.assertNotIn("\x07", entries[0].notes)
        self.assertEqual(len(warnings), 1)

    def test_http_get_rejects_non_https_urls(self) -> None:
        with self.assertRaises(ValueError):
            c.http_get_text("file:///etc/passwd")
        with self.assertRaises(ValueError):
            c.http_get_text("http://example.com/data.csv")


if __name__ == "__main__":
    unittest.main()
