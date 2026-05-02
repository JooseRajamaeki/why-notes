"""consult-why-notes: print notes anchored to a specific file, newest first."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path, PurePosixPath


def git(*args, cwd):
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (subprocess.SubprocessError, FileNotFoundError):
        return ""


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(
        prog="consult-why-notes",
        description=(
            "Print why-notes anchored to a specific file, newest first. Run "
            "before reading or editing a file to see prior architectural "
            "rationale. Later entries override earlier ones if they conflict — "
            "the most recent timestamp wins."
        ),
        epilog=(
            "Lookup root resolves in the same order as the recorder: "
            "$WHY_NOTES_DIR if set, otherwise <git-repo-root>/why-notes/, "
            "otherwise <cwd>/why-notes/. Notes are matched by --repo and the "
            "dir + basename derived from --file."
        ),
    )
    parser.add_argument(
        "--repo", required=True,
        help="Repo the file belongs to (must match the value used at recording time).",
    )
    parser.add_argument(
        "--file", required=True, dest="file_rel", metavar="FILE",
        help="Path of the file relative to --repo's root (e.g. 'src/auth/login.py').",
    )
    args = parser.parse_args()

    if "/" in args.repo or ".." in args.repo or args.repo.startswith("."):
        print(f"consult-why-notes: invalid --repo {args.repo!r}", file=sys.stderr)
        return 2

    fp = PurePosixPath(args.file_rel)
    if fp.is_absolute() or any(p == ".." for p in fp.parts) or not fp.name:
        print(f"consult-why-notes: invalid --file {args.file_rel!r}", file=sys.stderr)
        return 4

    cwd = Path(os.getcwd())
    env_dir = os.environ.get("WHY_NOTES_DIR")
    if env_dir:
        notes_root = Path(env_dir)
    else:
        repo_root = git("rev-parse", "--show-toplevel", cwd=cwd)
        notes_root = (Path(repo_root) if repo_root else cwd) / "why-notes"

    parent = str(fp.parent)
    target_dir = notes_root / args.repo
    if parent != ".":
        target_dir = target_dir / parent

    if not target_dir.is_dir():
        print(f"consult-why-notes: no notes directory at {target_dir}", file=sys.stderr)
        return 0

    expected_dir = "" if parent == "." else parent
    matches = []
    for f in target_dir.glob(f"{fp.name}-*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if data.get("basename") == fp.name and data.get("dir", "") == expected_dir:
            matches.append(data)

    if not matches:
        print(f"consult-why-notes: no notes for {args.repo}/{args.file_rel}", file=sys.stderr)
        return 0

    matches.sort(key=lambda d: d.get("timestamp", ""), reverse=True)

    print(f"Found {len(matches)} note(s) for {args.repo}/{args.file_rel} (newest first; respect most recent if conflicting):", file=sys.stderr)
    print()
    for i, n in enumerate(matches, 1):
        related = n.get("related", []) or []
        print(f"--- note {i}/{len(matches)} ---")
        print(f"uuid:      {n.get('uuid', '?')}")
        print(f"timestamp: {n.get('timestamp', '?')}")
        print(f"agent:     {n.get('agent', '?')}")
        print(f"model:     {n.get('model', '?')}")
        print(f"commit:    {n.get('commit', '?')}")
        print(f"branch:    {n.get('branch', '?')}")
        print(f"related:   {', '.join(related) if related else '(none)'}")
        print()
        print(n.get("note", ""))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
