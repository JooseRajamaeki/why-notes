"""consult: print notes anchored to a specific file plus those reachable via 'related' cross-references."""

import argparse
import os
import sys
from pathlib import Path

from note import (
    NotesStore,
    reconfigure_streams_utf8,
    validate_file_rel,
    validate_repo,
)


def print_note(n, label, show_location=False):
    related = n.related or []
    print(f"--- {label} ---")
    print(f"uuid:      {n.uuid or '?'}")
    if show_location:
        print(f"location:  {n.location()}")
    print(f"timestamp: {n.timestamp or '?'}")
    print(f"agent:     {n.agent or '?'}")
    print(f"model:     {n.model or '?'}")
    chain = n.commit if isinstance(n.commit, list) else ([n.commit] if n.commit else [])
    if len(chain) > 1:
        print(f"commit:    {chain[-1]}  (rewritten {len(chain) - 1}x; original {chain[0]})")
    else:
        print(f"commit:    {n.current_commit() or '?'}")
    print(f"branch:    {n.branch or '?'}")
    print(f"related:   {', '.join(related) if related else '(none)'}")
    print()
    print(n.note or "")
    print()


def main():
    reconfigure_streams_utf8((sys.stdout, sys.stderr))

    parser = argparse.ArgumentParser(
        prog="consult",
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
            "listed separately. Each loaded note's checksum is verified; "
            "corrupted notes are flagged on stderr."
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

    try:
        validate_repo(args.repo)
    except ValueError as e:
        print(f"consult: {e}", file=sys.stderr)
        return 2

    try:
        file_rel = validate_file_rel(args.file_rel)
    except ValueError as e:
        print(f"consult: {e}", file=sys.stderr)
        return 4

    cwd = Path(os.getcwd())
    store = NotesStore.resolve(cwd)

    primaries = store.primaries_for(args.repo, file_rel)
    if not primaries:
        if not store.root.is_dir():
            print(f"consult: no notes directory at {store.root}", file=sys.stderr)
        else:
            print(f"consult: no notes for {args.repo}/{args.file_rel}", file=sys.stderr)
        return 0

    primaries.sort(key=lambda n: n.timestamp or "", reverse=True)

    index = {u: n for u, (_, n) in store.index_by_uuid().items()}

    seen = {p.uuid for p in primaries if p.uuid}
    queue = []
    for p in primaries:
        queue.extend(p.related or [])

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
        queue.extend(n.related or [])

    related_notes.sort(key=lambda n: n.timestamp or "", reverse=True)

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

    corrupted = [n for n in (*primaries, *related_notes) if n.verify() == "corrupted"]
    legacy = sum(1 for n in (*primaries, *related_notes) if n.verify() == "no_checksum")
    if corrupted:
        print(file=sys.stderr)
        print(
            f"consult: WARNING — {len(corrupted)} note(s) failed checksum verification "
            "(content may have been altered since recording — accidentally or otherwise):",
            file=sys.stderr,
        )
        for n in corrupted:
            print(f"  {n.uuid}  {n.location()}", file=sys.stderr)
    if legacy:
        print(
            f"consult: {legacy} note(s) predate checksums and cannot be verified",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
