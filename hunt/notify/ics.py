"""iCalendar (.ics) export for interview reminders — imports into Google Calendar,
Outlook, or Apple Calendar without any OAuth integration."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def _fmt(dt: datetime) -> str:
    return dt.astimezone(ZoneInfo("UTC")).strftime("%Y%m%dT%H%M%SZ")


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def interview_ics(uid: str, company: str, title: str, start: datetime, minutes: int = 45,
                  location: str = "", notes: str = "", reminder_minutes: int = 60) -> str:
    end = start + timedelta(minutes=minutes)
    now = datetime.now(ZoneInfo("UTC"))
    return "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//InternshipHunt//EN", "CALSCALE:GREGORIAN", "BEGIN:VEVENT",
        f"UID:{uid}@internship-hunt", f"DTSTAMP:{_fmt(now)}", f"DTSTART:{_fmt(start)}", f"DTEND:{_fmt(end)}",
        f"SUMMARY:{_esc(f'Interview: {company} – {title}')}", f"LOCATION:{_esc(location)}", f"DESCRIPTION:{_esc(notes)}",
        "BEGIN:VALARM", "ACTION:DISPLAY", f"TRIGGER:-PT{reminder_minutes}M", "DESCRIPTION:Interview reminder", "END:VALARM",
        "END:VEVENT", "END:VCALENDAR", ""])
