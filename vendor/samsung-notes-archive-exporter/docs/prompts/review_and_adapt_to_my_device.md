# Prompt: Review And Adapt To My Device

Use this prompt with Codex, Claude, ChatGPT, or another coding assistant when adapting this project to a different phone, Samsung Notes version, Android version, language, screen size, or computer environment.

```text
You are helping me adapt a local Samsung Notes archive exporter to my own device.

Goal:
Export my own Samsung Notes through official visible UI flows into a local folder-preserving archive. Do not use root, private Samsung Cloud APIs, private app databases, token extraction, or any upload/sync route.

My environment:
- Phone model:
- Android version:
- Samsung Notes version:
- Computer OS:
- ADB path/version:
- Samsung Notes language:
- Screen resolution:

Safety rules:
1. Do not delete, move, modify, or upload notes.
2. Do not inspect private app storage under /data/data except for permission checks.
3. Use official Samsung Notes UI only.
4. Start with read-only probes and dry-runs.
5. Save raw screenshots/XML locally only; do not paste raw dumps into chat unless explicitly needed.
6. Use screenshot-first compact observations.

Tasks:
1. Inspect the repository structure and explain the current automation flow.
2. Check whether scripts and source code assume Galaxy S26 Plus, Korean UI labels, macOS, or this project's specific folder names.
3. Identify device/version-specific assumptions that may need editing.
4. Run or propose read-only ADB probes first.
5. Add or update tests before changing risky automation logic.
6. Keep generated personal exports, screenshots, XML dumps, and archives ignored by git.
7. Produce a short adaptation checklist and exact commands for my environment.

Do not start export actions until I explicitly approve them.
```
