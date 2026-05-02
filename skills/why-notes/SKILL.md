---
name: why-notes
description: Record the reasoning behind architectural decisions as they're made. Trigger when the user explains *why* a choice was made, alternatives are weighed, or a non-obvious workaround is introduced — so the rationale survives beyond the chat.
---

When a decision worth preserving comes up, pipe a short prose note into `skills/why-notes/src/skill.py` with `--agent`, `--model`, and `--repo` set. The script writes one JSON file per note under `why-notes/<repo>/` inside the cwd. Fields: `timestamp`, `agent`, `model`, `repo`, `branch`, `commit`, `note`. One file per note keeps them easy to ingest into other storage systems.

```bash
python3 skills/why-notes/src/skill.py --agent claude --model "opus 4.7" --repo my-app <<'EOF'
<what was decided and why — plain prose, no formatting needed>
EOF
```

- `--agent` — source of the note: `human`, `claude`, `openai`, etc.
- `--model` — model identifier (e.g. `"opus 4.7"`). Use `n/a` for human entries.
- `--repo` — name of the git repository the note refers to (the one being discussed, not necessarily the cwd).

All three are required. The cwd must be a git repository with at least one commit — the script exits non-zero otherwise, since every note needs a commit anchor.

Skip routine fixes, renames, dependency bumps, and anything the code or commit message already explains.

## Recording human input

When the user says something architectural worth preserving, record their words **verbatim** — copy the message into the heredoc unchanged. No paraphrasing, no summaries, no commentary, no reordering. Use `--agent human --model n/a`. If you also want to log your own analysis, do it as a separate entry with `--agent claude`.
