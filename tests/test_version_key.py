#!/usr/bin/env python3
"""Tests for the version-comparison helper used by `fenox update`.

The helper is loaded straight out of src/fenox_mobile_source.py, so the shipped
implementation is what runs (importing the module would execute the CLI).

Regression guard: comparing version strings directly made '2.9.0' look newer
than '2.10.0', so the updater would rebuild from an outdated local repo instead
of downloading the newer release.
"""
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parent.parent / "src" / "fenox_mobile_source.py"

chunks = [c for c in SRC.read_text().split("\ndef ") if c.startswith("_ver_key(")]
if not chunks:
    print("❌ _ver_key not found in src/fenox_mobile_source.py")
    sys.exit(1)

ns: dict = {}
exec("def " + chunks[0], ns)  # noqa: S102 — executes our own source text
ver_key = ns["_ver_key"]

failures = []


def check(desc, got, want):
    if got == want:
        print(f"  \033[32mok\033[0m   {desc}")
    else:
        print(f"  \033[31mFAIL\033[0m {desc} (got {got!r}, want {want!r})")
        failures.append(desc)


print("version comparison")
check("1.9.0 is older than 1.10.0", ver_key("1.9.0") < ver_key("1.10.0"), True)
check("1.99.99 is older than 1.100.0", ver_key("1.99.99") < ver_key("1.100.0"), True)
check("identical versions are equal", ver_key("1.0.0") == ver_key("1.0.0"), True)
check("leading 'v' is ignored", ver_key("v1.0.0") == ver_key("1.0.0"), True)
check("1.0 precedes 1.0.0", ver_key("1.0") < ver_key("1.0.0"), True)
check("numeric patch beats string order", ver_key("1.10.0") > ver_key("1.9.0"), True)
check("unparseable version sorts oldest", ver_key("dev") == (0,), True)

print(f"\n{len(failures)} failed" if failures else "\nall passed")
sys.exit(1 if failures else 0)
