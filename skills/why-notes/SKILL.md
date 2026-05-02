---
name: why-notes
description: Record the reasoning behind architectural decisions as they're made. Trigger when the user explains *why* a choice was made, alternatives are weighed, or a non-obvious workaround is introduced — so the rationale survives beyond the chat.
---

Pipe a prose note to `skills/why-notes/src/skill.py`. The script handles formatting, schema, metadata, and storage paths. Run it with `--help` for the full contract.

```bash
python3 skills/why-notes/src/skill.py --agent <human|claude|...> --model <name-or-model-id> --repo <repo> --file <path-within-repo> <<'EOF'
<prose>
EOF
```

Two rules the script can't enforce:

- **Verbatim human input.** When `--agent human`, copy the user's message into the heredoc unchanged — no paraphrasing or reordering.
- **Human's name as --model.** Ask once at session start what name to use; reuse it for every human entry that session.

Skip routine fixes, renames, dependency bumps, and anything the code or commit message already explains.
