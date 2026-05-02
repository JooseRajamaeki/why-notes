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
    parser = argparse.ArgumentParser(description="Record a why-note as a JSON file under why-notes/<repo>/<dirs>/.")
    parser.add_argument("--agent", required=True, help="Source of the note: human, claude, openai, etc.")
    parser.add_argument("--model", required=True, help="Model identifier, e.g. 'opus 4.7'. Use 'n/a' for humans.")
    parser.add_argument("--repo", required=True, help="Name of the git repository the note refers to.")
    parser.add_argument("--file", required=True, dest="file_rel",
                        help="Path of the file within --repo that the note is about, e.g. src/auth/login.py.")
    args = parser.parse_args()

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
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uuid": note_uuid,
        "agent": args.agent,
        "model": args.model,
        "repo": args.repo,
        "file": str(file_rel),
        "branch": branch,
        "commit": commit,
        "note": note,
    }

    filename = f"{file_rel.name}-{note_uuid}.json"
    out = notes_dir / filename
    out.write_text(json.dumps(record, indent=2) + "\n")
    print(f"why-notes: wrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
