"""why-notes recorder: pipe a prose note in; one JSON file is written per note, anchored to a file + commit."""

import argparse
import json
import os
import subprocess
import sys
import uuid as uuidlib
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


def git(*args, cwd):
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (subprocess.SubprocessError, FileNotFoundError):
        return ""


def main():
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
             "existing note (look them up via consult-why-notes).",
    )
    args = parser.parse_args()

    for u in args.related:
        try:
            uuidlib.UUID(u)
        except ValueError:
            print(f"why-notes: invalid uuid in --related: {u!r}", file=sys.stderr)
            return 5

    if "/" in args.repo or ".." in args.repo or args.repo.startswith("."):
        print(f"why-notes: invalid --repo {args.repo!r}", file=sys.stderr)
        return 2

    file_rel = PurePosixPath(args.file_rel)
    if file_rel.is_absolute() or any(p == ".." for p in file_rel.parts) or not file_rel.name:
        print(f"why-notes: invalid --file {args.file_rel!r}", file=sys.stderr)
        return 4

    cwd = Path(os.getcwd())
    commit = git("rev-parse", "--short", "HEAD", cwd=cwd)
    if not commit:
        print(f"why-notes: no git commit at {cwd} — notes require a commit anchor", file=sys.stderr)
        return 3
    branch = git("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd)

    note = sys.stdin.read().strip()
    if not note:
        print("why-notes: empty input, nothing recorded", file=sys.stderr)
        return 1

    env_dir = os.environ.get("WHY_NOTES_DIR")
    if env_dir:
        notes_root = Path(env_dir)
    else:
        repo_root = git("rev-parse", "--show-toplevel", cwd=cwd)
        notes_root = (Path(repo_root) if repo_root else cwd) / "why-notes"

    parent = str(file_rel.parent)
    notes_dir = notes_root / args.repo
    if parent != ".":
        notes_dir = notes_dir / parent
    notes_dir.mkdir(parents=True, exist_ok=True)

    note_uuid = str(uuidlib.uuid4())
    dir_in_repo = "" if parent == "." else parent
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uuid": note_uuid,
        "agent": args.agent,
        "model": args.model,
        "repo": args.repo,
        "dir": dir_in_repo,
        "basename": file_rel.name,
        "branch": branch,
        "commit": commit,
        "related": args.related,
        "note": note,
    }

    filename = f"{file_rel.name}-{note_uuid}.json"
    out = notes_dir / filename
    out.write_text(json.dumps(record, indent=2) + "\n")
    print(f"why-notes: wrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
