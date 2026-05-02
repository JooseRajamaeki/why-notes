"""why-notes recorder: pipe a prose note in; one JSON file is written per note."""

import argparse
import json
import os
import secrets
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def git(*args, cwd):
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (subprocess.SubprocessError, FileNotFoundError):
        return ""


def main():
    parser = argparse.ArgumentParser(description="Record a why-note as a JSON file under why-notes/<repo>/.")
    parser.add_argument("--agent", required=True, help="Source of the note: human, claude, openai, etc.")
    parser.add_argument("--model", required=True, help="Model identifier, e.g. 'opus 4.7'. Use 'n/a' for humans.")
    parser.add_argument("--repo", required=True, help="Name of the git repository the note refers to.")
    args = parser.parse_args()

    if "/" in args.repo or ".." in args.repo or args.repo.startswith("."):
        print(f"why-notes: invalid --repo {args.repo!r}", file=sys.stderr)
        return 2

    cwd = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    commit = git("rev-parse", "--short", "HEAD", cwd=cwd)
    if not commit:
        print(f"why-notes: no git commit at {cwd} — notes require a commit anchor", file=sys.stderr)
        return 3
    branch = git("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd)

    note = sys.stdin.read().strip()
    if not note:
        print("why-notes: empty input, nothing recorded", file=sys.stderr)
        return 1

    notes_dir = cwd / "why-notes" / args.repo
    notes_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    record = {
        "timestamp": now.isoformat(),
        "agent": args.agent,
        "model": args.model,
        "repo": args.repo,
        "branch": branch,
        "commit": commit,
        "note": note,
    }

    filename = f"{now.strftime('%Y%m%dT%H%M%SZ')}_{secrets.token_hex(4)}.json"
    out = notes_dir / filename
    out.write_text(json.dumps(record, indent=2) + "\n")
    print(f"why-notes: wrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
