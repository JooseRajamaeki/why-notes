---
name: why-notes
description: Capture and surface architectural rationale. Trigger to RECORD when the user explains *why* a choice was made, alternatives are weighed, or a non-obvious workaround is introduced. Trigger to CONSULT before reading or editing a file in this project, so new decisions don't unknowingly contradict earlier reasoning.
---

Two scripts share one data model (`src/note.py`).

**Consult** prior rationale before editing a file:

```bash
python3 skills/why-notes/src/consult.py --repo <repo> --file <path-within-repo>
```

Notes print newest-first; later entries override earlier ones. Tampered checksums are flagged on stderr.

**Record** rationale at the moment it surfaces:

```bash
python3 skills/why-notes/src/record.py --agent <human|claude|...> --model <name-or-model-id> --repo <repo> --file <path-within-repo> [--related <uuid>...] <<'EOF'
<prose>
EOF
```

Pass `--related` UUIDs (look them up via `consult.py`) when this decision builds on existing notes.

Run either script with `--help` for the full contract.

Two rules the script can't enforce:

- **Verbatim human input.** When `--agent human`, copy the user's message into the heredoc unchanged — no paraphrasing or reordering.
- **Human's name as --model.** Ask once at session start what name to use; reuse it for every human entry that session.

Skip routine fixes, renames, dependency bumps, and anything the code or commit message already explains.
