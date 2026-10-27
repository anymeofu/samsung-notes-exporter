# Contributing

Contributions are welcome, especially safety guards, parser tests, device-adaptation notes, and archive-format improvements.

Before opening a pull request:

1. Run `PYTHONPATH=src python3 -m unittest discover -s tests`.
2. Run `git diff --check`.
3. Confirm no personal exports, screenshots, UI dumps, device serials, note titles, or private folder names are included.
4. Keep real-device changes behind explicit `--execute` flags and fail closed on uncertain screens.

Do not submit raw Samsung Notes XML, screenshots, note contents, account data, or generated archives. Use harmless synthetic fixtures and redacted metadata instead.
