#!/usr/bin/env python3
"""The phone-data layer: parsing a content provider, without a phone attached.

Reading messages and the call log means running `content query` on the phone and
parsing text back out of it. Two things went wrong while this was written, and
both are guarded here:

  * the local shell ate the quotes meant for the device shell, so `--sort
    'date DESC'` arrived as two arguments, the phone printed its usage text, and
    a full inbox read back as "no messages" — with a success exit code;
  * a message body can contain ", " or an "=", so naive splitting on commas
    turned message text into extra columns.

No device, no adb: the provider output is canned, so this runs anywhere.
"""
import datetime
import importlib.util
import os
import pathlib
import re
import shlex
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "fenox.py"

failures = []


def check(desc, ok, detail=""):
    info = f" ({detail})" if detail else ""
    print(f"  \033[32mok\033[0m   {desc}{info}" if ok else f"  \033[31mFAIL\033[0m {desc}{info}")
    if not ok:
        failures.append(desc)


home = tempfile.mkdtemp(prefix="fenox-phone-")
os.environ["HOME"] = home
os.environ.pop("FENOX_PLUGIN_DIR", None)
spec = importlib.util.spec_from_file_location("fenox_phone", SRC)
fx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fx)


# --- parsing what the provider prints ---------------------------------------
print("content query parsing")
rows = fx.parse_content_rows(
    "Row: 0 _id=1, body=Hello, world, how are you=good\n"
    "Row: 1 _id=2, body=first line\n"
    "second line, still the body\n"
    "Date: 2026-09-18 03:04\n")
check("two rows parsed", len(rows) == 2, str(len(rows)))
check("a comma inside a body stays in the body",
      rows and rows[0]["body"] == "Hello, world, how are you=good", rows[0].get("body") if rows else "")
check("an '=' inside a body stays in the body",
      rows and rows[1]["body"].startswith("first line"), rows[1].get("body") if len(rows) > 1 else "")
check("a wrapped value is folded back, newline kept",
      len(rows) > 1 and rows[1]["body"] == "first line\nsecond line, still the body",
      repr(rows[1]["body"]) if len(rows) > 1 else "")
check("the trailing Date: line is not folded into a value",
      rows and rows[-1]["body"].endswith("body"), rows[-1].get("body") if rows else "")
check("an empty value is kept as empty",
      fx.parse_content_rows("Row: 0 _id=3, body=")[0]["body"] == "")

print("failures are reported, never hidden")
check("a permission denial is recognised",
      "permission" in fx.content_error("Error while accessing provider:sms\njava.lang.SecurityException: "
                                       "Permission Denial: reading requires READ_SMS"))
check("the device's usage text is recognised as a rejected command",
      "rejected the command" in fx.content_error("usage: adb shell content [subcommand] [options]"))
check("clean output has no error", fx.content_error("Row: 0 _id=1") == "")

# --- what actually reaches the device shell ---------------------------------
print("quoting at the adb boundary")
captured = {}


def fake_run(argv, **kwargs):
    captured["argv"] = argv
    captured["shell"] = kwargs.get("shell")

    class Done:
        returncode = 0
        stdout = "Row: 0 _id=1"
        stderr = ""

    return Done()


real_run = fx.subprocess.run
fx.subprocess.run = fake_run
try:
    fx.content_query("DEV", fx.SMS_URI, ["_id"], sort="date DESC")
finally:
    fx.subprocess.run = real_run
check("no shell=True: the local shell cannot mangle the command",
      captured.get("shell") is not True, f"shell={captured.get('shell')!r}")
check("the whole command is one argument, so the device keeps its quotes",
      captured.get("argv") == ["adb", "-s", "DEV", "shell",
                              "content query --uri content://sms --projection _id --sort 'date DESC'"],
      str(captured.get("argv")))

# --- numbers, names and time ------------------------------------------------
print("numbers, names and time")
MOBILE, LOCAL = "+821012345678", "01012345678"
check("the same number matches in its local and international forms",
      fx._number_key(MOBILE) == fx._number_key(LOCAL),
      f"{fx._number_key(MOBILE)} vs {fx._number_key(LOCAL)}")
check("a number shows as its contact name",
      fx.number_label(MOBILE, {fx._number_key(LOCAL): "Mom"}) == f"Mom ({MOBILE})",
      fx.number_label(MOBILE, {fx._number_key(LOCAL): "Mom"}))
check("an unknown number stays as itself",
      fx.number_label(MOBILE, {}) == MOBILE)
check("a short code still resolves",
      fx.number_label("5551234", {"5551234": "Work"}) == "Work (5551234)",
      fx.number_label("5551234", {"5551234": "Work"}))
check("redaction keeps the last four digits only",
      fx.number_label("+821012345678", {"1012345678": "Mom"}, redact=True) == "…5678",
      fx.number_label("+821012345678", {"1012345678": "Mom"}, redact=True))
check("a redacted body reports its size, not its words",
      fx._redact_body("secret") == "[6 characters hidden]", fx._redact_body("secret"))
check("an epoch timestamp is readable", fx._fmt_when(1758100000000).startswith("17 Sep 2025"),
      fx._fmt_when(1758100000000))
check("a junk timestamp does not raise", fx._fmt_when("not-a-date") == "—")

# --- threads, assembled from three provider passes --------------------------
print("threads")
FAKE = {
    fx.SMS_THREADS_URI:
        "Row: 0 thread_id=1, msg_count=5, snippet=Hello, there\n"
        "Row: 1 thread_id=2, msg_count=2, snippet=Bye now",
    fx.SMS_URI:                       # sorted date DESC, so the newest thread comes first
        "Row: 0 thread_id=2, address=+15550001111, date=1700000600000\n"
        "Row: 1 thread_id=1, address=+15550002222, date=1700000000000",
    fx.SMS_INBOX_URI: "Row: 0 thread_id=1\nRow: 1 thread_id=1\nRow: 2 thread_id=2",
}

asked = []


def fake_shell(dev_id, cmd, timeout=None):
    asked.append(cmd)
    # Match the --uri value exactly: "content://sms" is a substring of both
    # "content://sms/inbox" and "content://sms/conversations".
    wanted = re.search(r"--uri (\S+)", cmd)
    if wanted and wanted.group(1) in FAKE:
        return True, FAKE[wanted.group(1)]
    return False, ""


real_shell = fx.adb_shell
fx.adb_shell = fake_shell
try:
    threads, error = fx.phone_threads(
        "DEV", names={fx._number_key("15550001111"): "Ada"}, limit=None)
    check("no error reading a good device", error == "", error)
    check("every thread is listed", len(threads) == 2, str(len(threads)))
    check("threads are newest first", [t["thread_id"] for t in threads] == ["2", "1"],
          str([t["thread_id"] for t in threads]))
    check("the newest thread carries its date and address",
          threads[0]["when"] != "—" and threads[0]["address"] == "+15550001111",
          f"{threads[0]['when']} {threads[0]['address']}")
    check("unread counts come from the inbox pass",
          [t["unread"] for t in threads] == [1, 2], str([t["unread"] for t in threads]))
    check("a contact name is applied to the thread", threads[0]["label"] == "Ada (+15550001111)",
          threads[0]["label"])
    check("a snippet keeps its commas", threads[1]["snippet"] == "Hello, there",
          threads[1]["snippet"])
    only_unread, _ = fx.phone_threads("DEV", unread_only=True, limit=None)
    check("--unread drops threads with nothing unread", len(only_unread) == 2, str(len(only_unread)))
    limited, _ = fx.phone_threads("DEV", limit=1)
    check("--limit is applied client-side (the device has no --limit)",
          len(limited) == 1, str(len(limited)))

    # A provider that refuses must surface as an error, not as an empty inbox.
    fx.adb_shell = lambda dev, cmd, timeout=None: (
        False, "Error while accessing provider:sms java.lang.SecurityException: Permission Denial")
    blocked, error = fx.phone_threads("DEV")
    check("a refusing provider reports the refusal", blocked is None and error,
          f"{blocked} / {error}")

    # --- one conversation ---
    fx.adb_shell = lambda dev, cmd, timeout=None: (
        True,
        "Row: 0 _id=1, address=+15550001111, date=1700000000000, type=1, read=0, body=hi\n"
        "Row: 1 _id=2, address=+15550001111, date=1700000060000, type=2, read=1, body=ok then")
    messages, error = fx.phone_thread_messages("DEV", 5)
    check("a conversation reads oldest first", [m["body"] for m in messages] == ["hi", "ok then"],
          str([m["body"] for m in messages]))
    check("received and sent are told apart",
          [m["direction"] for m in messages] == ["in", "out"],
          str([m["direction"] for m in messages]))
    check("unread state is carried per message", messages[0]["read"] is False)
    bad, error = fx.phone_thread_messages("DEV", "5; DROP TABLE sms")
    check("a non-numeric thread id is refused before it reaches the device",
          bad is None and "not a thread id" in error, error)

    updates = []
    fx.adb_shell = lambda dev, cmd, timeout=None: (updates.append(cmd), (True, "Updated: 2"))[1]
    marked, note = fx.phone_mark_thread_read("DEV", "5")
    check("marking read targets one thread, and only the unread rows",
          marked and updates and "thread_id=5 AND read=0" in updates[-1], str(updates[-1:]))
    check("marking read reports how many it changed", "2" in note, note)
finally:
    fx.adb_shell = real_shell

# --- the call log: the same provider, with its own traps ---------------------
print("call log values")
check("an unset provider column reads as blank, not as the word NULL",
      fx._provider_text("NULL") == "" and fx._provider_text(None) == ""
      and fx._provider_text("(Unknown)") == "",
      f"{fx._provider_text('NULL')!r} {fx._provider_text('(Unknown)')!r}")
check("a real name keeps its spaces trimmed",
      fx._provider_text("  Queen Mother  ") == "Queen Mother")
check("type codes become the words a person uses",
      [fx.call_kind(code) for code in ("1", "2", "3", "4", "5", "6", "7")]
      == ["incoming", "outgoing", "missed", "voicemail", "rejected", "blocked",
          "answered elsewhere"],
      str([fx.call_kind(code) for code in ("1", "3")]))
check("an unrecognised type code is just a call", fx.call_kind("99") == "call",
      fx.call_kind("99"))
check("a duration reads as a length, and never as 0s",
      [fx._fmt_duration(value) for value in (0, "45", 64, 3725, None)]
      == ["—", "45s", "1m 04s", "1h 02m", "—"],
      str([fx._fmt_duration(value) for value in (0, 64, 3725)]))

print("call filters")
check("one kind is a plain equality",
      fx.calls_where(kinds=["missed"]) == "type=3", fx.calls_where(kinds=["missed"]))
check("several kinds are grouped, so a later AND cannot bind to only the last",
      (fx.calls_where(kinds=["incoming", "outgoing"]) or "").startswith("(type=1 OR type=2)"),
      fx.calls_where(kinds=["incoming", "outgoing"]))
check("a window filters on the date",
      "date>=" in (fx.calls_where(days=7) or ""), fx.calls_where(days=7))
check("days=0 means the whole log, with no clause at all",
      fx.calls_where(days=0) is None, str(fx.calls_where(days=0)))
check("a search matches the number or the cached name",
      fx.calls_where(search="ada") == "(number LIKE '%ada%' OR name LIKE '%ada%')",
      fx.calls_where(search="ada"))
check("a quote in a search cannot break out of the clause",
      "'%o''brien%'" in (fx.calls_where(search="o'brien") or ""),
      fx.calls_where(search="o'brien"))
check("one number is matched on its last nine digits, whatever the formatting",
      fx.calls_where(number="+234 803 123 4567") == "number LIKE '%031234567%'",
      fx.calls_where(number="+234 803 123 4567"))
check("the local form of the same number produces the same clause",
      fx.calls_where(number="08031234567") == fx.calls_where(number="+2348031234567"),
      fx.calls_where(number="08031234567"))

print("call log rows")
CALLS_FAKE = (
    # Sorted date DESC by the device, so row 0 is the newest. The dialler's own
    # `name` is filled for one of them, the literal NULL for the others, and the
    # last has no number at all (a withheld or private call).
    "Row: 0 _id=3916, number=08031234567, date=1700000600000, duration=0, type=3, "
    "new=1, name=Queen Mother\n"
    "Row: 1 _id=3915, number=+2348031234567, date=1700000000000, duration=125, type=2, "
    "new=0, name=NULL\n"
    "Row: 2 _id=3914, number=, date=1699999000000, duration=8, type=1, new=1, name=NULL")

ASKED = []


def fake_calls_shell(dev_id, cmd, timeout=None):
    ASKED.append(cmd)
    if "content update" in cmd:
        return True, ""                      # the device reports nothing on a no-op
    return True, CALLS_FAKE


CALLS_NAMES = {fx._number_key("8031234567"): "Ada"}
real_shell_back = fx.adb_shell
fx.adb_shell = fake_calls_shell
try:
    calls, error = fx.phone_calls("DEV", names=CALLS_NAMES, days=30)
    check("no error reading a good call log", error == "", error)
    check("calls come back newest first",
          [c["id"] for c in calls] == ["3916", "3915", "3914"],
          str([c["id"] for c in calls]))
    check("the device's own cached name wins",
          calls[0]["label"] == "Queen Mother", calls[0]["label"])
    check("a NULL name falls back to the contacts lookup, not the word NULL",
          calls[1]["label"] == "Ada (+2348031234567)", calls[1]["label"])
    check("a withheld number is reported as unknown",
          calls[2]["label"] == "unknown", calls[2]["label"])
    check("calls are typed by outcome",
          [c["kind"] for c in calls] == ["missed", "outgoing", "incoming"],
          str([c["kind"] for c in calls]))
    check("lengths are readable, and a call that never connected shows —",
          [c["duration"] for c in calls] == ["—", "2m 05s", "8s"],
          str([c["duration"] for c in calls]))
    check("the new-call flag is carried", [c["new"] for c in calls] == [True, False, True],
          str([c["new"] for c in calls]))
    check("--limit is applied client-side (the device has no --limit)",
          len(fx.phone_calls("DEV", limit=1)[0]) == 1)
    ASKED.clear()
    fx.phone_calls("DEV", kinds=["missed"], days=0, number="+2348031234567")
    # The clause is quoted for the device shell, so compare against the quoting
    # the code itself produces rather than the clause in its bare form.
    check("kinds and a number reach the device as one clause",
          any(shlex.quote(f"type=3 AND number LIKE '%031234567%'") in cmd for cmd in ASKED),
          str(ASKED[-1:]))

    # A provider that refuses must surface as an error, not as an empty history.
    fx.adb_shell = lambda dev, cmd, timeout=None: (
        False, "Error while accessing provider:call_log java.lang.SecurityException: "
               "Permission Denial: requires READ_CALL_LOG")
    blocked, error = fx.phone_calls("DEV")
    check("a refused call log reports the refusal", blocked is None and error,
          f"{blocked} / {error}")

    # --- marking calls seen: a write, and never a silent one ---
    fx.adb_shell = fake_calls_shell
    ASKED.clear()
    cleared = {"3916", "3915"}      # what the update is treated as having cleared

    def fake_seen_shell(dev_id, cmd, timeout=None):
        ASKED.append(cmd)
        if "content update" in cmd:
            return True, ""            # the device prints nothing when it changes rows
        ids = re.search(r"_id IN \(([^)]*)\)", cmd)
        rows = "\n".join(f"Row: {n} _id={one.strip()}, new={0 if one.strip() in cleared else 1}"
                         for n, one in enumerate((ids.group(1).split(",") if ids else [])))
        return True, rows

    fx.adb_shell = fake_seen_shell
    ok, note = fx.phone_mark_calls_seen("DEV", ["3916", "3915"])
    check("marking seen targets exactly the rows shown, and only that flag",
          ok and any("_id IN (3916,3915)" in cmd and "new:i:0" in cmd for cmd in ASKED),
          str(ASKED[:1]))
    check("an empty reply from the device is confirmed by reading the flag back",
          "2 of 2" in note, note)
    # 3914 is still flagged new on the phone, so a run that claims to have marked
    # it must not be believed: the count comes from the read-back.
    ok, note = fx.phone_mark_calls_seen("DEV", ["3914"])
    check("a call still flagged new is not counted as marked",
          "0 of 1" in note, note)
    ok, note = fx.phone_mark_calls_seen("DEV", ["abc", ""])
    check("a non-numeric id is refused before it reaches the device",
          ok is False and "no calls" in note, note)
    fx.adb_shell = lambda dev, cmd, timeout=None: (False, "Permission Denial: requires WRITE_CALL_LOG")
    ok, note = fx.phone_mark_calls_seen("DEV", ["3916"])
    check("a refused write says so instead of claiming success", ok is False and note, note)
finally:
    fx.adb_shell = real_shell_back

check("the breakdown leads with missed, and abbreviates in/out",
      fx.phone_call_counts([{"kind": "outgoing"}, {"kind": "missed"},
                            {"kind": "incoming"}, {"kind": "missed"}])
      == "2 missed · 1 in · 1 out",
      fx.phone_call_counts([{"kind": "outgoing"}, {"kind": "missed"}]))

# --- the CLI reaches the right resource, and never dials by accident ---------
print("call log CLI")


class Args:
    """argparse's namespace, with an unset flag reading as None like a real one."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getattr__(self, name):
        return None


dispatched, dialled = [], []
real_phone_bits = (fx.resolve_phone_device, fx.print_calls, fx.phone_contacts,
                   fx.phone_calls, fx._call_number)
real_print_calls = fx.print_calls
fx.resolve_phone_device = lambda alias=None: "DEV"
fx.print_calls = lambda dev, args: dispatched.append((dev, args.resource))
fx.action_phone(Args(resource="calls"))
check("`fenox phone calls` dispatches to the call log, not to messages",
      dispatched == [("DEV", "calls")], str(dispatched))

fx.print_calls = real_print_calls          # back to the real one for the dial checks
fx.phone_contacts = lambda dev: {}
fx.phone_calls = lambda *a, **k: ([{"id": "1", "number": "08030000000",
                                    "label": "08030000000", "when": "now",
                                    "date": "1", "kind": "missed", "duration": "—",
                                    "new": True}], "")
fx._call_number = lambda dev, number: dialled.append(number)
out = fx.print_calls("DEV", Args(resource="calls", dial=True, limit=5))
check("--dial without --from refuses to guess who to call",
      out is False and dialled == [], f"{out} / {dialled}")
out = fx.print_calls("DEV", Args(resource="calls", dial=True, from_number="08030000000",
                                  limit=5))
check("--dial places exactly the --from number", dialled == ["08030000000"], str(dialled))
and_out = fx.print_calls("DEV", Args(resource="calls", json_out=True, limit=5))
check("reading the log never dials", and_out is True and len(dialled) == 1, str(dialled))
(fx.resolve_phone_device, fx.print_calls, fx.phone_contacts, fx.phone_calls,
 fx._call_number) = real_phone_bits

# --- contacts and calendar: the same traps, with their own column names ------
print("contacts")
CONTACTS_FAKE = (
    "Row: 0 contact_id=1, display_name=Queen Mother, data1=+234 803 123 4567\n"
    "Row: 1 contact_id=1, display_name=Queen Mother, data1=+2348031234567\n"
    "Row: 2 contact_id=2, display_name=NULL, data1=08030000001\n"
    "Row: 3 contact_id=3, display_name=Work line, data1=08030000002")
fx.adb_shell = lambda dev, cmd, timeout=None: (
    False, "") if False else (True, CONTACTS_FAKE)
contacts, error = fx.phone_contact_rows("DEV")
check("contacts read without error", error == "", error)
check("the same number twice is one contact",
      len(contacts) == 3, str(len(contacts)))
check("a NULL name is not shown as the word NULL",
      any(c["name"] == "(no name)" for c in contacts),
      str([c["name"] for c in contacts]))
ASKED.clear()
fx.adb_shell = lambda dev, cmd, timeout=None: (ASKED.append(cmd), (True, ""))[1]
fx.phone_contact_rows("DEV", search="08030000002")
expected_num = shlex.quote(
    "(display_name LIKE '%08030000002%' OR data1 LIKE '%08030000002%')")
check("search matches the number as well as the name",
      any(expected_num in cmd for cmd in ASKED), str(ASKED[-1:]))
ASKED.clear()
fx.phone_contact_rows("DEV", search="o'brien")
# The where is quoted for the device shell, so compare against the quoting the
# code itself produces rather than the bare clause.
expected = shlex.quote(
    "(display_name LIKE '%o''brien%' OR data1 LIKE '%o''brien%')")
check("a quote in a contact search cannot break out of the clause",
      any(expected in cmd for cmd in ASKED), str(ASKED[-1:]))
check("phone number types get their words", fx._number_type("2") == "mobile"
      and fx._number_type("NULL") == "")

print("calendar")
START_MS, END_MS = 1700000000000, 1700604800000
CAL_FAKE = (
    "Row: 0 event_id=9, title=Momma's Box Battle , begin=1700000000000, end=1700003600000, "
    "allDay=0, eventLocation=Studio 5, calendar_id=7\n"
    "Row: 1 event_id=8, title=추분, begin=1700086400000, end=1700172800000, allDay=1, "
    "eventLocation=NULL, calendar_id=33")
fx.adb_shell = lambda dev, cmd, timeout=None: (True, CAL_FAKE)
events, error = fx.phone_events("DEV", days=7)
check("events read without error", error == "", error)
check("both occurrences are listed", len(events) == 2, str(len(events)))
check("a recurring event's occurrence carries its own day", events[1]["all_day"] is True)
check("an event's span reads as a range", "–" in fx._fmt_range(events[0]),
      fx._fmt_range(events[0]))
check("an all-day event says so", "all day" in fx._fmt_range(events[1]),
      fx._fmt_range(events[1]))
check("an unset location is blank, not NULL", events[1]["where"] == "")
found, _ = fx.phone_events("DEV", days=7, search="momma")
check("search matches the title case-insensitively",
      len(found) == 1 and found[0]["id"] == "9", str([e['id'] for e in found]))
found, _ = fx.phone_events("DEV", days=7, calendar_id=33)
check("a calendar filter keeps only its own events",
      len(found) == 1 and found[0]["id"] == "8", str([e['id'] for e in found]))
check("a junk time is refused, not invented", fx._parse_when("gibberish") is None)
check("HH:MM resolves to a real timestamp", fx._parse_when("09:30") is not None)
check("a full timestamp resolves exactly",
      fx._parse_when("2026-09-18 09:30") == int(datetime.datetime(
          2026, 9, 18, 9, 30).timestamp() * 1000))

print("calendar writes and call removal")
BINDS = []
fx.adb_shell = lambda dev, cmd, timeout=None: (BINDS.append(cmd), (True, ""))[1]
ok, note = fx.phone_add_event("DEV", "Standup", 1700000000000, 1700003600000)
check("adding an event binds timestamps as longs (an int would overflow)",
      any("--bind dtstart:l:" in cmd for cmd in BINDS), str(BINDS[-1:]))
check("the timezone is declared", any("eventTimezone:s:UTC" in cmd for cmd in BINDS))
ok, note = fx.phone_add_event("DEV", "", 1, 2)
check("an untitled event is refused locally", ok is False and "title" in note, note)
ok, note = fx.phone_add_event("DEV", "Backwards", 200, 100)
check("an end before its start is refused locally", ok is False and "end" in note, note)

DELETED = []
fx.adb_shell = lambda dev, cmd, timeout=None: (
    DELETED.append(cmd), (True, ""))[1]
fx.adb_shell = lambda dev, cmd, timeout=None: (
    DELETED.append(cmd),
    (True, "") if "content delete" in cmd else (True, "Row: 0 _id=9"))[1]
ok, note = fx.phone_delete_call("DEV", "9")
check("a removal targets exactly one call",
      any("_id=9" in cmd and "content delete" in cmd for cmd in DELETED), str(DELETED[-1:]))
check("a removal the phone did not do is reported honestly",
      ok is False and "still lists" in note, note)
DELETED.clear()
fx.adb_shell = lambda dev, cmd, timeout=None: (
    DELETED.append(cmd),
    (True, "") if "content delete" in cmd else (True, ""))[1]
ok, note = fx.phone_delete_call("DEV", "9")
check("a removal is verified by reading back", ok is True and "removed" in note, note)
DELETED.clear()
ok, note = fx.phone_delete_call("DEV", "9; DROP")
check("a non-numeric call id never reaches the device",
      ok is False and not DELETED, note)

check("the breakdown still reads right after all of this",
      fx.phone_call_counts([{"kind": "missed"}]) == "1 missed",
      fx.phone_call_counts([{"kind": "missed"}]))

print(f"\n{len(failures)} failed" if failures else "\nall passed")
sys.exit(1 if failures else 0)
