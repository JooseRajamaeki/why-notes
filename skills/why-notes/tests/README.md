# Tests

Run from the repo root:

```bash
python3 -m unittest discover -s skills/why-notes/tests -t skills/why-notes/tests
```

`test_note.py` covers the data model in `src/note.py` (checksum, validators, store I/O). `test_cli.py` runs `record.py` and `consult.py` end-to-end via subprocess in a throwaway git repo with `WHY_NOTES_DIR` pointed at a tempdir.

No third-party dependencies — stdlib `unittest` only.
