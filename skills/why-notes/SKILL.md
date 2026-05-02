---
name: why-notes
description: Record the reasoning behind architectural decisions as they're made. Trigger when the user explains *why* a choice was made, alternatives are weighed, or a non-obvious workaround is introduced — so the rationale survives beyond the chat.
---

When a decision worth preserving comes up, pipe a short prose note into `skills/why-notes/src/skill.py` with `--agent`, `--model`, `--repo`, and `--file` set. The script writes one JSON file per note at `<root>/<repo>/<dirs>/<basename>-<uuid>.json`, where `<dirs>` mirrors `--file`'s parent path inside `--repo`. One file per note keeps notes easy to ingest into other storage systems.

`<root>` is resolved as: `$WHY_NOTES_DIR` if set, otherwise `<git-repo-root>/why-notes/` if the cwd is inside a git repo, otherwise `<cwd>/why-notes/`. Commit is stored in the JSON, not the filename.

```bash
python3 skills/why-notes/src/skill.py --agent claude --model "opus 4.7" --repo my-app --file src/auth/login.py <<'EOF'
<what was decided and why — plain prose, no formatting needed>
EOF
```

JSON fields: `timestamp`, `uuid`, `agent`, `model`, `repo`, `file`, `branch`, `commit`, `note`.

- `--agent` — source of the note: `human`, `claude`, `openai`, etc.
- `--model` — model identifier (e.g. `"opus 4.7"`). Use `n/a` for human entries.
- `--repo` — name of the git repository the note refers to (the one being discussed, not necessarily the cwd).
- `--file` — path of the file within `--repo` that this note is about (e.g. `src/auth/login.py`).

All four are required. The cwd must be a git repository with at least one commit — the script exits non-zero otherwise, since every note needs a commit anchor.

Skip routine fixes, renames, dependency bumps, and anything the code or commit message already explains.

## Recording human input

When the user says something architectural worth preserving, record their words **verbatim** — copy the message into the heredoc unchanged. No paraphrasing, no summaries, no commentary, no reordering. Use `--agent human --model n/a`. If you also want to log your own analysis, do it as a separate entry with `--agent claude`.
