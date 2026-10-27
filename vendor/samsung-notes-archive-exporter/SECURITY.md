# Security Policy

## Scope

This project controls ADB and visible Samsung Notes UI. Treat it as powerful local automation, not as a harmless file converter.

The project must not access Samsung Notes private databases, bypass Knox, extract account tokens, reverse engineer private cloud APIs, upload notes, or delete/move/modify source notes.

## Reporting A Problem

Do not include note contents, screenshots, raw UI dumps, device serials, account information, or private folder names in a public issue.

For a suspected security issue, use GitHub's private vulnerability reporting if enabled for this repository. Otherwise contact the maintainer through the GitHub profile before publishing details.

For ordinary reproducible bugs, redact all personal data and include only:

- phone model and Android/Samsung Notes versions
- macOS/Linux/Windows version
- command and dry-run output
- a harmless test-folder description
- the smallest relevant sanitized log excerpt

## User Safety

Always back up Samsung Notes first. Review the code before granting USB debugging or running `--execute`. Keep `input_exports/`, `output_archive/`, `ui_dumps/`, `observations/`, and `conversion_workspace/` local and untracked.
