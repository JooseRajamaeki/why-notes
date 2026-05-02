"""why-notes recorder: pipe a prose note in; one JSON file is written per note, anchored to a file + commit."""

import argparse
import os
import sys
from pathlib import Path

from note import (
    Note,
    NotesStore,
    git,
    reconfigure_streams_utf8,
    validate_file_rel,
    validate_repo,
    validate_uuids,
)


def main():
    reconfigure_streams_utf8((sys.stdin, sys.stdout, sys.stderr))

    parser = argparse.ArgumentParser(
        prog="why-notes",
        description=(
            "Record the reasoning behind an architectural decision. Pipe a "
            "prose note to stdin; the script wraps it with metadata and writes "
            "one JSON file per note, anchored to a specific file at a specific "
            "commit so the rationale survives beyond the chat. Skip routine "
            "fixes, renames, and anything the code or commit message already "
            "explains."
        ),
        epilog=(
            "Storage location resolves in order: $WHY_NOTES_DIR if set, "
            "otherwise <git-repo-root>/why-notes/, otherwise <cwd>/why-notes/. "
            "The note lands at <root>/<repo>/<dir>/<basename>-<uuid>.json. The "
            "cwd must be a git repository with at least one commit (every note "
            "needs a commit anchor). When --agent is 'human', record the "
            "user's words verbatim — no paraphrasing or summarising."
        ),
    )
    parser.add_argument(
        "--agent", required=True,
        help="Source of the note. Use 'human' for a user, or an AI identifier "
             "('claude', 'openai', etc.) for AI-authored entries.",
    )
    parser.add_argument(
        "--model", required=True,
        help="For AI sources, the model identifier (e.g. 'opus 4.7', 'gpt-5'). "
             "For human sources, the human's name (ask the user once per session).",
    )
    parser.add_argument(
        "--repo", required=True,
        help="Name of the git repository the note refers to. May differ from "
             "the cwd's repo when one repo's notes describe code in another.",
    )
    parser.add_argument(
        "--file", required=True, dest="file_rel", metavar="FILE",
        help="Path of the file the note is about, relative to --repo's root "
             "(e.g. 'src/auth/login.py'). Split into 'dir' + 'basename' in the JSON.",
    )
    parser.add_argument(
        "--related", nargs="*", default=[], metavar="UUID",
        help="UUIDs of related why-notes (space-separated). Use to link "
             "architectural principles that span multiple files; UUIDs of any "
             "existing note (look them up via consult).",
    )
    parser.add_argument(
        "--repo-url", default=None, dest="repo_url", metavar="URL",
        help="URL of the git repository the note refers to (e.g. "
             "'git@github.com:owner/repo.git' or "
             "'https://github.com/owner/repo'). If omitted, falls back to "
             "the cwd's 'origin' remote URL. Pass explicitly when --repo "
             "differs from the cwd's repo.",
    )
    parser.add_argument(
        "--max-chars", type=int, default=1000, dest="max_chars", metavar="N",
        help="Maximum note length in characters for non-human entries "
             "(default: 1000). Human entries are never truncated or rejected. "
             "If you (the AI agent) believe a note legitimately needs to "
             "exceed this limit, STOP and consult the human user before "
             "raising it — do not silently bump the value.",
    )
    args = parser.parse_args()

    if args.max_chars < 1:
        print(f"why-notes: --max-chars must be >= 1 (got {args.max_chars})", file=sys.stderr)
        return 6

    try:
        validate_uuids(args.related)
    except ValueError as e:
        print(f"why-notes: {e}", file=sys.stderr)
        return 5

    try:
        validate_repo(args.repo)
    except ValueError as e:
        print(f"why-notes: {e}", file=sys.stderr)
        return 2

    try:
        file_rel = validate_file_rel(args.file_rel)
    except ValueError as e:
        print(f"why-notes: {e}", file=sys.stderr)
        return 4

    cwd = Path(os.getcwd())
    commit = git("rev-parse", "--short", "HEAD", cwd=cwd)
    if not commit:
        print(f"why-notes: no git commit at {cwd} — notes require a commit anchor", file=sys.stderr)
        return 3
    branch = git("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd)
    repo_url = args.repo_url if args.repo_url is not None else git("remote", "get-url", "origin", cwd=cwd)

    note_text = sys.stdin.read().strip()
    if not note_text:
        print("why-notes: empty input, nothing recorded", file=sys.stderr)
        return 1

    if args.agent != "human" and len(note_text) > args.max_chars:
        print(
            f"why-notes: note is {len(note_text)} chars, exceeds --max-chars "
            f"limit of {args.max_chars} for non-human agent {args.agent!r}. "
            f"Tighten the note, or consult the human user before raising "
            f"--max-chars.",
            file=sys.stderr,
        )
        return 7

    note = Note.create(
        agent=args.agent,
        model=args.model,
        repo=args.repo,
        repo_url=repo_url,
        file_rel=file_rel,
        branch=branch,
        commit=commit,
        related=args.related,
        note=note_text,
    )

    store = NotesStore.resolve(cwd)
    out_path = store.write(note)
    print(f"why-notes: wrote {out_path}", file=sys.stderr)

    for rel_uuid in args.related:
        patched = store.add_backlink(rel_uuid, note.uuid)
        if patched is None:
            print(
                f"why-notes: warning: related uuid {rel_uuid!r} not found; skipping back-link",
                file=sys.stderr,
            )
        else:
            print(f"why-notes: back-linked {patched}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
