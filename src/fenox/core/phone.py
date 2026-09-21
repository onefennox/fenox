"""The phone's own data, read through Android content providers.

Messages, calls, contacts and calendar are read by the adb shell user on a stock
device — nothing is installed on the phone and no root is needed. Writes are
never implicit; each one is a deliberate, separate call.

A provider that refuses access must be visible, so shell commands report failure
instead of collapsing into output that would read as an empty inbox.
"""
from __future__ import annotations

import datetime
import re
import shlex
import subprocess
import time

SMS_URI = "content://sms"
SMS_INBOX_URI = "content://sms/inbox"
SMS_THREADS_URI = "content://sms/conversations"
CONTACT_PHONES_URI = "content://com.android.contacts/data/phones"
CALL_LOG_URI = "content://call_log/calls"
CALENDAR_URI = "content://com.android.calendar/calendars"
CALENDAR_EVENTS_URI = "content://com.android.calendar/events"
CALENDAR_INSTANCES_URI = "content://com.android.calendar/instances/when/{start}/{end}"

CALL_KINDS = {"1": "incoming", "2": "outgoing", "3": "missed", "4": "voicemail",
              "5": "rejected", "6": "blocked", "7": "answered elsewhere"}
CALL_KIND_KEYS = {"incoming": "1", "outgoing": "2", "missed": "3", "voicemail": "4",
                  "rejected": "5", "blocked": "6", "answered elsewhere": "7"}

CONTENT_ROW = re.compile(r"^Row:\s*\d+\s*(.*)$")
CONTENT_FIELD = re.compile(r",\s+(?=[A-Za-z_][A-Za-z0-9_]*=)")


def shell(serial: str, command: str, timeout: int = 40) -> tuple[bool, str]:
    """(ok, output) for a device shell command, with provider errors surfaced."""
    try:
        proc = subprocess.run(
            ["adb", "-s", serial, "shell", command],
            capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
        )
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    output = (proc.stdout + proc.stderr).strip()
    return (proc.returncode == 0 and not content_error(output)), output


def content_error(output: str) -> str:
    """The provider's own complaint when a query was refused, else ''."""
    if "Permission Denial" in output or "SecurityException" in output:
        return "permission denied — this ROM restricts what the shell user may read"
    for line in output.splitlines():
        if line.startswith("usage:") or "unknown subcommand" in line:
            return f"the phone rejected the command: {line.strip()[:120]}"
        for marker in ("Error while accessing provider", "Unknown URI", "no such column", "IllegalArgumentException"):
            if marker in line:
                return line.strip()[:200]
    return ""


def parse_content_rows(output: str) -> list[dict]:
    """Rows from `content query` as dicts.

    The format is `Row: <n> column=value, column=value`. A value may itself
    contain ", ", so a comma only starts a column when what follows looks like
    `name=`. A value containing a newline spills onto the next line and is folded
    back into that column.
    """
    rows: list[dict] = []
    for raw in output.splitlines():
        line = raw.strip()
        match = CONTENT_ROW.match(line)
        if not match:
            if rows and line and not line.startswith("Date:") and "=" not in line:
                last = rows[-1]
                key = next(reversed(last), None)
                if key:
                    last[key] = f"{last[key]}\n{line}"
            continue
        row: dict[str, str] = {}
        for field in CONTENT_FIELD.split(match.group(1)):
            if "=" in field:
                name, value = field.split("=", 1)
                row[name.strip()] = value
        rows.append(row)
    return rows


def content_query(serial: str, uri: str, projection: list[str] | None = None,
                  where: str | None = None, sort: str | None = None) -> tuple[bool, list[dict], str]:
    command = f"content query --uri {uri}"
    if projection:
        command += f" --projection {':'.join(projection)}"
    if where:
        command += f" --where {shlex.quote(where)}"
    if sort:
        command += f" --sort {shlex.quote(sort)}"
    ok, output = shell(serial, command)
    if not ok:
        return False, [], content_error(output) or output[:200]
    return True, parse_content_rows(output), ""


def _provider_text(value) -> str:
    text = str(value or "").strip()
    return "" if text.upper() in ("NULL", "(UNKNOWN)", "UNKNOWN") else text


def _number_key(digits: str) -> str:
    """Match numbers by their last nine digits; country codes vary between stores."""
    return digits[-9:] if len(digits) >= 9 else digits


def _fmt_when(ms) -> str:
    try:
        when = datetime.datetime.fromtimestamp(int(ms) / 1000)
    except (TypeError, ValueError, OSError):
        return "—"
    now = datetime.datetime.now()
    if when.date() == now.date():
        return when.strftime("%H:%M")
    if when.year == now.year:
        return when.strftime("%d %b %H:%M")
    return when.strftime("%d %b %Y")


def _fmt_duration(seconds) -> str:
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return "—"
    if total <= 0:
        return "—"
    if total < 60:
        return f"{total}s"
    if total < 3600:
        return f"{total // 60}m {total % 60:02d}s"
    return f"{total // 3600}h {(total % 3600) // 60:02d}m"


# -- contacts --------------------------------------------------------------

def contacts(serial: str) -> dict[str, str]:
    """{number key: contact name} so numbers can be shown as people."""
    ok, rows, _ = content_query(serial, CONTACT_PHONES_URI, ["display_name", "data1"])
    names: dict[str, str] = {}
    for row in rows if ok else []:
        digits = re.sub(r"\D", "", row.get("data1", ""))
        name = (row.get("display_name") or "").strip()
        if name and name != "(Unknown)" and digits:
            names.setdefault(_number_key(digits), name)
    return names


def number_label(number: str, names: dict[str, str]) -> str:
    digits = re.sub(r"\D", "", number or "")
    if not digits:
        return number or "unknown"
    name = names.get(_number_key(digits))
    if name and name != number:
        return f"{name} ({number})"
    return number


def contact_rows(serial: str, search: str | None = None, limit: int | None = None) -> tuple[list[dict] | None, str]:
    where = None
    if search:
        safe = str(search).replace("'", "''")
        where = f"(display_name LIKE '%{safe}%' OR data1 LIKE '%{safe}%')"
    ok, rows, error = content_query(serial, CONTACT_PHONES_URI, ["contact_id", "display_name", "data1"],
                                    where=where, sort="display_name ASC")
    if not ok:
        return None, error
    seen, result = set(), []
    for row in rows:
        name = _provider_text(row.get("display_name"))
        number = _provider_text(row.get("data1"))
        if not number:
            continue
        key = (name.lower(), re.sub(r"\D", "", number))
        if key in seen:
            continue
        seen.add(key)
        result.append({"id": row.get("contact_id", ""), "name": name or "(no name)", "number": number})
    return (result[:limit] if limit else result), ""


# -- messages --------------------------------------------------------------

def threads(serial: str, names: dict[str, str] | None = None, unread_only: bool = False,
            limit: int | None = None) -> tuple[list[dict] | None, str]:
    names = names or {}
    ok, grouped, error = content_query(serial, SMS_THREADS_URI, ["thread_id", "msg_count", "snippet"])
    if not ok:
        return None, error
    ok, latest, error = content_query(serial, SMS_URI, ["thread_id", "address", "date"], sort="date DESC")
    if not ok:
        return None, error
    ok, unread_rows, _ = content_query(serial, SMS_INBOX_URI, ["thread_id"], where="read=0")
    unread: dict[str, int] = {}
    for row in unread_rows if ok else []:
        key = row.get("thread_id", "")
        unread[key] = unread.get(key, 0) + 1
    head: dict[str, dict] = {}
    for row in latest:
        head.setdefault(row.get("thread_id", ""), row)
    result = []
    for row in grouped:
        thread_id = row.get("thread_id", "")
        newest = head.get(thread_id, {})
        address = newest.get("address", "")
        result.append({
            "thread_id": thread_id,
            "address": address,
            "label": number_label(address, names),
            "date": newest.get("date", ""),
            "when": _fmt_when(newest.get("date")),
            "count": row.get("msg_count", ""),
            "unread": unread.get(thread_id, 0),
            "snippet": " ".join(str(row.get("snippet", "")).split()),
        })
    result.sort(key=lambda t: int(t["date"] or 0), reverse=True)
    if unread_only:
        result = [t for t in result if t["unread"]]
    if limit:
        result = result[:limit]
    return result, ""


def thread_messages(serial: str, thread_id, names: dict[str, str] | None = None,
                    limit: int = 50) -> tuple[list[dict] | None, str]:
    names = names or {}
    try:
        clause = f"thread_id={int(thread_id)}"
    except (TypeError, ValueError):
        return None, f"not a thread id: {thread_id}"
    ok, rows, error = content_query(serial, SMS_URI, ["_id", "address", "date", "type", "read", "body"],
                                    where=clause, sort="date ASC")
    if not ok:
        return None, error
    messages = []
    for row in rows:
        kind = {"1": "in", "2": "out", "3": "draft", "4": "out", "5": "failed"}.get(str(row.get("type") or ""), "in")
        messages.append({
            "id": row.get("_id", ""),
            "address": row.get("address", ""),
            "label": number_label(row.get("address", ""), names),
            "when": _fmt_when(row.get("date")),
            "date": row.get("date", ""),
            "direction": kind,
            "read": row.get("read", "1") == "1",
            "body": row.get("body", "") or "(empty message)",
        })
    return (messages[-limit:] if limit else messages), ""


def mark_thread_read(serial: str, thread_id) -> tuple[bool, str]:
    try:
        clause = f"thread_id={int(thread_id)} AND read=0"
    except (TypeError, ValueError):
        return False, f"not a thread id: {thread_id}"
    ok, output = shell(serial, f"content update --uri {SMS_URI} --where {shlex.quote(clause)} --bind read:i:1")
    if not ok:
        return False, content_error(output) or output[:200]
    count = re.search(r"Updated:?\s*(\d+)", output)
    return True, f"marked {count.group(1) if count else 'the'} message(s) read"


# -- calls -----------------------------------------------------------------

def call_kind(code) -> str:
    return CALL_KINDS.get(str(code or "").strip(), "call")


def calls_where(kinds=None, days=None, search=None, number=None) -> str | None:
    clauses = []
    codes = [CALL_KIND_KEYS[kind] for kind in (kinds or []) if kind in CALL_KIND_KEYS]
    if len(codes) == 1:
        clauses.append(f"type={codes[0]}")
    elif codes:
        clauses.append("(" + " OR ".join(f"type={code}" for code in codes) + ")")
    if days:
        clauses.append(f"date>={int((time.time() - int(days) * 86400) * 1000)}")
    if search:
        safe = str(search).replace("'", "''")
        clauses.append(f"(number LIKE '%{safe}%' OR name LIKE '%{safe}%')")
    if number:
        digits = re.sub(r"\D", "", str(number))
        tail = digits[-9:] if len(digits) >= 9 else digits
        if tail:
            clauses.append(f"number LIKE '%{tail}%'")
    return " AND ".join(clauses) or None


def calls(serial: str, names: dict[str, str] | None = None, kinds=None, days=30,
          search=None, number=None, limit=None) -> tuple[list[dict] | None, str]:
    names = names or {}
    ok, rows, error = content_query(
        serial, CALL_LOG_URI,
        ["_id", "number", "date", "duration", "type", "new", "name"],
        where=calls_where(kinds, days, search, number), sort="date DESC")
    if not ok:
        return None, error
    result = []
    for row in rows:
        address = _provider_text(row.get("number"))
        cached = _provider_text(row.get("name"))
        result.append({
            "id": row.get("_id", ""),
            "number": address,
            "label": cached if cached and cached != "(Unknown)" else number_label(address, names),
            "when": _fmt_when(row.get("date")),
            "date": row.get("date", ""),
            "kind": call_kind(row.get("type")),
            "duration": _fmt_duration(row.get("duration")),
            "new": row.get("new", "0") == "1",
        })
    return (result[:limit] if limit else result), ""


def mark_calls_seen(serial: str, call_ids) -> tuple[bool, str]:
    ids = [str(i) for i in call_ids if str(i).strip().isdigit()]
    if not ids:
        return False, "no calls to mark"
    clause = f"_id IN ({','.join(ids)})"
    ok, output = shell(serial, f"content update --uri {CALL_LOG_URI} --where {shlex.quote(clause)} --bind new:i:0")
    if not ok:
        return False, content_error(output) or output[:200]
    ok, rows, _ = content_query(serial, CALL_LOG_URI, ["_id", "new"], where=clause)
    marked = len(ids)
    if ok:
        marked = sum(1 for row in rows if row.get("new") != "1")
    return True, f"marked {marked} of {len(ids)} call(s) as seen"


def delete_call(serial: str, call_id) -> tuple[bool, str]:
    try:
        call_id = int(str(call_id).strip())
    except (TypeError, ValueError):
        return False, "not a call id"
    ok, output = shell(serial, f"content delete --uri {CALL_LOG_URI} --where {shlex.quote(f'_id={call_id}')}")
    if not ok:
        return False, content_error(output) or output[:200]
    ok, rows, _ = content_query(serial, CALL_LOG_URI, ["_id"], where=f"_id={call_id}")
    if ok:
        return (not rows), ("removed from the phone's call log" if not rows
                            else "the phone still lists the call — it may refuse deletes")
    return True, "delete sent (could not verify)"


# -- calendar --------------------------------------------------------------

def calendars(serial: str) -> tuple[list[dict] | None, str]:
    ok, rows, error = content_query(serial, CALENDAR_URI, ["_id", "name", "account_name", "calendar_displayName"])
    if not ok:
        return None, error
    result = []
    for row in rows:
        name = (_provider_text(row.get("calendar_displayName")) or _provider_text(row.get("name"))
                or _provider_text(row.get("account_name")) or f"calendar {row.get('_id', '?')}")
        result.append({
            "id": row.get("_id", ""),
            "name": name,
            "account": _provider_text(row.get("account_name")),
        })
    return result, ""


def events(serial: str, days: int = 7, calendar_id=None, search=None,
           limit=None) -> tuple[list[dict] | None, str]:
    start = int(time.time() * 1000)
    end = start + int(days or 0) * 86400_000
    ok, rows, error = content_query(
        serial, CALENDAR_INSTANCES_URI.format(start=start, end=end),
        ["event_id", "title", "begin", "end", "allDay", "eventLocation", "calendar_id"],
        sort="begin ASC")
    if not ok:
        return None, error
    result = []
    for row in rows:
        title = _provider_text(row.get("title")) or "(untitled)"
        if search:
            needle = str(search).lower()
            if needle not in title.lower() and needle not in _provider_text(row.get("eventLocation")).lower():
                continue
        if calendar_id and row.get("calendar_id") != str(calendar_id):
            continue
        result.append({
            "id": row.get("event_id", ""),
            "title": title,
            "when": _fmt_when(row.get("begin")),
            "begin": row.get("begin", ""),
            "end": row.get("end", ""),
            "all_day": row.get("allDay", "0") == "1",
            "where": _provider_text(row.get("eventLocation")),
            "calendar_id": row.get("calendar_id", ""),
        })
    return (result[:limit] if limit else result), ""


def add_event(serial: str, title: str, begin_ms, end_ms, calendar_id=1) -> tuple[bool, str]:
    title = str(title or "").strip()
    if not title:
        return False, "the event needs a title"
    try:
        begin_ms, end_ms = int(begin_ms), int(end_ms)
    except (TypeError, ValueError):
        return False, "start and end must be timestamps in milliseconds"
    if end_ms <= begin_ms:
        return False, "the end must come after the start"
    ok, output = shell(
        serial,
        f"content insert --uri {CALENDAR_EVENTS_URI} "
        f"--bind title:s:{shlex.quote(title)} "
        f"--bind dtstart:l:{begin_ms} --bind dtend:l:{end_ms} "
        f"--bind eventTimezone:s:UTC --bind calendar_id:i:{int(calendar_id)}")
    if not ok:
        return False, content_error(output) or output[:200]
    ok, rows, _ = content_query(serial, CALENDAR_EVENTS_URI, ["_id"],
                                where=f"title={shlex.quote(title)} AND dtstart={begin_ms}")
    if ok and rows:
        return True, f"added '{title}' to the phone's calendar"
    return True, f"added '{title}' (not verified on the phone)"
