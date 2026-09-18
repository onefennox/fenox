## What and why

<!-- What does this change, and what problem does it solve? Focus on the "why". -->

## How I tested it

<!--
Paste the commands you ran and their outcome. "Ran tests/test_release_e2e.sh
against a locally built binary" beats a summary of the diff.
-->

- [ ] `python -m py_compile src/fenox.py`
- [ ] `python src/fenox.py --help`
- [ ] `bash -n install.sh`
- [ ] `bash tests/test_install_checksum.sh`
- [ ] `python tests/test_version_key.py`

## Checklist

- [ ] I added or updated a test that fails without this change
- [ ] I updated `CHANGELOG.md` under `Unreleased`
- [ ] `VERSION` and `FENOX_VERSION` still match (if either changed)
- [ ] No new runtime dependencies beyond `rich`
- [ ] Any download or install path still verifies a checksum and fails closed
- [ ] Docs (`README.md`, `CONTRIBUTING.md`) updated where behaviour changed

## Related issues

<!-- e.g. Closes #123 -->
