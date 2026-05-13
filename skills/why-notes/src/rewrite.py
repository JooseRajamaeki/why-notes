"""rewrite: update why-notes after a git rebase or amend.

Designed to be invoked by git's `post-rewrite` hook, which feeds
`<old-sha> <new-sha>` pairs on stdin for every rewritten commit. For
each matching note in the local corpus, appends the new short SHA to
`commit` and recomputes the checksum.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from note import (
    NotesStore,
    git,
    reconfigure_streams_utf8,
)


def short_sha(full_sha: str, cwd) -> str:
    """Abbreviate a full SHA the same way record.py captures it."""
    out = git("rev-parse", "--short", full_sha, cwd=cwd)
    return out or full_sha


def parse_pairs(lines):
    """Yield (old, new) tuples from `<old> <new>` lines. Skips blanks/garbage."""
    for raw in lines:
        parts = raw.strip().split()
        if len(parts) >= 2:
            yield parts[0], parts[1]


def apply_rewrites(store: NotesStore, pairs, cwd) -> tuple[int, int]:
    """Walk the corpus and append new SHAs to any note matching an old SHA.

    Matches the note's current short commit against the full old SHA by
    prefix, since the corpus stores short SHAs but git's post-rewrite
    emits full ones. Returns (notes_updated, pairs_matched).
    """
    # Pre-abbreviate the new SHAs once, and remember which pairs ever matched.
    resolved = [(old, short_sha(new, cwd=cwd)) for old, new in pairs]
    matched_pairs = set()
    updated = 0
    for path, note in store.iter_notes():
        cur = note.current_commit()
        if not cur:
            continue
        new_short = None
        for old, new_s in resolved:
            if old.startswith(cur):
                new_short = new_s
                matched_pairs.add((old, new_s))
                break
        if new_short is None:
            continue
        if note.append_commit(new_short):
            path.write_text(
                json.dumps(note.to_dict(), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            updated += 1
    return updated, len(matched_pairs)


def main():
    reconfigure_streams_utf8((sys.stdin, sys.stdout, sys.stderr))

    parser = argparse.ArgumentParser(
        prog="rewrite",
        description=(
            "Patch why-notes after a git rebase or amend so their `commit` "
            "anchors stay pointed at live history. Designed for git's "
            "post-rewrite hook, which feeds `<old-sha> <new-sha>` pairs on "
            "stdin. Each matching note gets the new short SHA appended to "
            "its commit chain and its checksum recomputed."
        ),
        epilog=(
            "Corpus lookup follows the same rule as record/consult: "
            "$WHY_NOTES_DIR if set, else <git-repo-root>/why-notes/, else "
            "<cwd>/why-notes/. Notes are matched by short-SHA prefix; "
            "pairs that don't match any note are silently skipped."
        ),
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--stdin", action="store_true",
        help="Read `<old-sha> <new-sha>` pairs from stdin, one per line "
             "(the format git's post-rewrite hook emits).",
    )
    src.add_argument(
        "--map", action="append", default=[], metavar="OLD=NEW",
        help="One-off rewrite pair, e.g. `--map abc123=def456`. Repeatable.",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress the summary line on stderr.",
    )
    args = parser.parse_args()

    if args.stdin:
        pairs = list(parse_pairs(sys.stdin))
    else:
        pairs = []
        for entry in args.map:
            if "=" not in entry:
                print(f"rewrite: bad --map value {entry!r} (expected OLD=NEW)", file=sys.stderr)
                return 2
            old, new = entry.split("=", 1)
            pairs.append((old.strip(), new.strip()))

    if not pairs:
        if not args.quiet:
            print("rewrite: no rewrite pairs received; nothing to do", file=sys.stderr)
        return 0

    cwd = Path(os.getcwd())
    store = NotesStore.resolve(cwd)
    if not store.root.is_dir():
        if not args.quiet:
            print(f"rewrite: no notes directory at {store.root}", file=sys.stderr)
        return 0

    updated, matched = apply_rewrites(store, pairs, cwd=cwd)
    if not args.quiet:
        print(
            f"rewrite: updated {updated} note(s) across {matched} matched "
            f"pair(s) of {len(pairs)} received",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
