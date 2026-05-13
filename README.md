# why-notes

An agent skill for capturing — and later surfacing — the *reasoning* behind architectural decisions while code is being written, so the rationale survives beyond the chat.

## Why this exists

Code review, commit messages, and inline comments capture *what* changed. They rarely capture *why* a decision was made, which alternatives were rejected, or what constraint forced a workaround. That reasoning rots fast: by the time someone needs it (a refactor, a regression, an onboarding read), the original conversation is gone.

`why-notes` records the reasoning at the moment it surfaces, anchors each entry to a specific file at a specific commit, and stores it as an append-only JSON corpus that's easy to query — by hand, by another script, or by a future agent.

## The skill

A single skill (`skills/why-notes/`) ships two entry-point scripts that share one data model (`src/note.py`):

### `src/record.py` — the recorder

Pipe a prose note to the recorder; the script wraps it with metadata and writes one JSON file per note.

**Example invocation** (illustrative — `my-app`, `src/auth/login.py`, and the JWT rationale below are placeholders, not real values from this repo):

```bash
python3 skills/why-notes/src/record.py \
  --agent claude --model "opus 4.7" \
  --repo my-app --file src/auth/login.py \
  [--related <uuid>...] <<'EOF'
We chose JWT over session cookies because the API is stateless and we
need the same token to validate from a CDN edge worker. Considered
sticky-session cookies (rejected: regional failover) and signed
cookies (rejected: 4kB header limit on the affected route).
EOF
```

Run `--help` for the full contract. See `skills/why-notes/SKILL.md` for the agent-facing trigger conventions and the verbatim rule for human input.

### `src/consult.py` — the lookup

Before reading or editing a file, surface the prior rationale anchored to it. Notes print newest-first; when entries conflict, the most recent timestamp wins. Each loaded note's checksum is verified; corrupted notes are flagged on stderr.

**Example invocation** (placeholder values — substitute the repo and file you're about to work on):

```bash
python3 skills/why-notes/src/consult.py --repo my-app --file src/auth/login.py
```

## Storage layout

Each note is an independent JSON file at:

```
<root>/<repo>/<dir>/<basename>-<uuid>.json
```

`<root>` resolves in this order:
1. `$WHY_NOTES_DIR` if set,
2. `<git-repo-root>/why-notes/` if the cwd is inside a git repo,
3. `<cwd>/why-notes/` otherwise.

One JSON per note (rather than an aggregate log) makes the corpus trivially ingestible into databases or document stores. All location metadata lives in the JSON itself, so notes survive being extracted from their directory hierarchy.

## JSON schema

| Field       | Type       | Description                                                                              |
|-------------|------------|------------------------------------------------------------------------------------------|
| `timestamp` | string     | ISO 8601 UTC timestamp of when the note was recorded.                                    |
| `uuid`      | string     | UUIDv4. Suffix of the filename; referenced by other notes' `related`.                    |
| `version`   | string     | Schema version the note was written under (current: `"1"`). Omitted on pre-versioning notes. |
| `agent`     | string     | Source: `human` for users, `claude` / `openai` / etc. for AI sources.                    |
| `model`     | string     | AI model id (e.g. `opus 4.7`) for AI sources; the human's name for human sources.        |
| `repo`      | string     | Git repository the note refers to (may differ from the cwd).                             |
| `dir`       | string     | Parent directory of the noted file, relative to the repo root (`""` if at root).         |
| `basename`  | string     | File name within the repo.                                                               |
| `branch`    | string     | Git branch of the cwd repo at recording time.                                            |
| `commit`    | string     | Short git commit hash of the cwd repo at recording time. Required.                       |
| `repo_url` | string     | Git remote URL of the repo at recording time (omitted if unavailable).                   |
| `related`   | `string[]` | UUIDs of related notes for cross-referencing principles that span files.                 |
| `note`      | string     | Free-form prose: the rationale, constraint, or tradeoff being recorded.                  |
| `checksum`  | string     | SHA-256 over the immutable fields (everything except `repo_url`, `related`, `branch`). New immutable fields (currently `version`) are folded into the checksum only when present, so legacy notes still verify. |

`dir` is deliberately repo-relative — never relative to `$WHY_NOTES_DIR` or the cwd — so notes don't leak personal local-filesystem layout when shared.

## Conventions

- **Verbatim human input.** When `--agent human`, the user's words are recorded unchanged. No paraphrasing, no summarising. Different humans (or the same human across sessions) are disambiguated by `--model <name>`.
- **Commit anchor required.** The recorder fails if the cwd is not in a git repo with at least one commit. Every note ties to a codebase snapshot.
- **Recency wins.** When notes conflict, the newer one supersedes. `consult.py` surfaces newest-first to make this obvious.
- **Append-only corpus.** Existing JSON files under `why-notes/` are immutable history. Don't edit or delete them by hand; the only legitimate mutations are adding new notes (each is a new file) and the recorder's automatic backlink patches to `related`.
- **Skip the obvious.** Don't record what the code already shows or the commit message already explains. Notes are for the *why* that would otherwise be lost.
- **Standard library only.** Scripts in this repo must not import anything outside the Python standard library. No `pip install`, no `requirements.txt`, no virtualenv — the tools must run on a bare-bones machine with only `python3` and `git` available. Reach for the stdlib (or shell out to `git`) before introducing any third-party dependency.

## Repository structure

```
.
├── README.md                       (this file)
├── skills/
│   └── why-notes/                  the skill (record + consult)
│       ├── SKILL.md                trigger guidance for agents
│       └── src/
│           ├── note.py             Note + NotesStore classes (shared)
│           ├── record.py           recorder CLI
│           └── consult.py          lookup CLI
└── why-notes/                      the recorded corpus
    └── <repo>/<dir>/<basename>-<uuid>.json
```

The recursive `why-notes/` path looks odd at first glance: outermost is this repository's root, then the literal `why-notes/` corpus folder, then `<repo>` (the repo each note refers to). When this skill is dropped into another project, that project's notes about its own files would land at `<other-project>/why-notes/<other-project>/...`.
