# Prompt: Connection Troubleshooting

Use this prompt when ADB, USB, MTP, or device authorization is not working.

```text
Help me troubleshoot connecting my Android Galaxy phone to my computer for local Samsung Notes export automation.

My environment:
- Phone model:
- Android version:
- Computer OS:
- Cable type:
- USB mode shown on phone:
- USB debugging enabled?:
- `adb version` output:
- `adb devices` output:
- MTP app or file browser behavior:

Rules:
1. Do not ask me to root the phone or bypass Knox.
2. Do not suggest private Samsung Cloud APIs.
3. Prefer read-only diagnostics.
4. Explain what each command does before running it.
5. Keep personal note contents out of logs.

Please:
1. Diagnose likely causes.
2. Give me a short ordered checklist.
3. Separate ADB debugging from MTP/file-transfer debugging.
4. Tell me what phone screen prompts I should expect.
5. Give exact safe commands for macOS/Linux/Windows as appropriate.
```
