"""consult-why-notes: print notes anchored to a specific file plus those reachable via 'related' cross-references."""

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


def print_note(n, label, show_location=False):
    related = n.get("related") or []
    print(f"--- {label} ---")
    print(f"uuid:      {n.get('uuid', '?')}")
    if show_location:
        d = n.get("dir") or ""
        loc = f"{n.get('repo', '?')}/" + (f"{d}/" if d else "") + n.get("basename", "?")
        print(f"location:  {loc}")
    print(f"timestamp: {n.get('timestamp', '?')}")
    print(f"agent:     {n.get('agent', '?')}")
    print(f"model:     {n.get('model', '?')}")
    print(f"commit:    {n.get('commit', '?')}")
    print(f"branch:    {n.get('branch', '?')}")
    print(f"related:   {', '.join(related) if related else '(none)'}")
    print()
    print(n.get("note", ""))
    print()


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(
        prog="consult-why-notes",
        description=(
            "Print why-notes anchored to a specific file, plus any reachable "
            "via 'related' cross-references, newest first. Run before reading "
            "or editing a file to see prior architectural rationale. Later "
            "entries override earlier ones if they conflict — the most recent "
            "timestamp wins."
        ),
        epilog=(
            "Lookup root resolves in the same order as the recorder: "
            "$WHY_NOTES_DIR if set, otherwise <git-repo-root>/why-notes/, "
            "otherwise <cwd>/why-notes/. Primary notes are matched by --repo "
            "and the dir + basename derived from --file. Related notes are "
            "found by transitively following each primary's 'related' UUID "
            "list across the entire local notes corpus; cycles are detected "
            "and unresolved UUIDs (e.g. references into another corpus) are "
            "listed separately."
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
    primaries = []
    for f in target_dir.glob(f"{fp.name}-*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if data.get("basename") == fp.name and data.get("dir", "") == expected_dir:
            primaries.append(data)

    if not primaries:
        print(f"consult-why-notes: no notes for {args.repo}/{args.file_rel}", file=sys.stderr)
        return 0

    primaries.sort(key=lambda d: d.get("timestamp", ""), reverse=True)

    index = {}
    for f in notes_root.rglob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        u = d.get("uuid")
        if u:
            index[u] = d

    seen = {p["uuid"] for p in primaries if p.get("uuid")}
    queue = []
    for p in primaries:
        queue.extend(p.get("related") or [])

    related_notes = []
    unresolved = []
    while queue:
        u = queue.pop(0)
        if u in seen:
            continue
        seen.add(u)
        n = index.get(u)
        if n is None:
            unresolved.append(u)
            continue
        related_notes.append(n)
        queue.extend(n.get("related") or [])

    related_notes.sort(key=lambda d: d.get("timestamp", ""), reverse=True)

    print(
        f"Found {len(primaries)} primary note(s) for {args.repo}/{args.file_rel} "
        "(newest first; respect most recent if conflicting):"
    )
    print()
    for i, n in enumerate(primaries, 1):
        print_note(n, label=f"primary {i}/{len(primaries)}")

    if related_notes:
        print(f"Related notes reachable via cross-references ({len(related_notes)}, newest first):")
        print()
        for i, n in enumerate(related_notes, 1):
            print_note(n, label=f"related {i}/{len(related_notes)}", show_location=True)

    if unresolved:
        uniq = sorted(set(unresolved))
        print(f"Unresolved related UUIDs (not found in local corpus): {', '.join(uniq)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
