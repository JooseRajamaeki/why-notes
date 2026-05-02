---
name: consult-why-notes
description: Before reading or editing a file, look up prior architectural rationale recorded via the why-notes skill. Trigger any time you're about to work on a file in this project, so new decisions don't unknowingly contradict earlier reasoning.
---

Run `python3 skills/consult-why-notes/src/skill.py --repo <repo> --file <path-within-repo>` to print all notes anchored to a file. The script sorts newest-first and handles location resolution.

If multiple entries conflict, **respect the most recent timestamp** — earlier reasoning may have been superseded.

Run with `--help` for the full contract.
