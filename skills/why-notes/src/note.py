"""why-notes data model: Note (one record) and NotesStore (the corpus).

Both record.py and consult.py import from here. The classes own the
serialization format, checksum integrity, path resolution, and corpus
indexing — keep CLI concerns out of this module.
"""

import hashlib
import json
import os
import subprocess
import sys
import uuid as uuidlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


SCHEMA_VERSION = "3.0.0"

# Canonical fields hashed into the checksum for newly-created notes. Each note
# stores its own `checksum_fields` list, so this constant only seeds new notes;
# verification reads the list off the note itself. `"checksum_fields"` is in
# the list, making the checksum self-referential — altering the field list
# invalidates the hash.
CHECKSUM_FIELDS = (
    "agent", "basename", "checksum_fields", "commit", "dir",
    "model", "note", "timestamp", "uuid", "version",
)
SERIALIZED_FIELDS = (
    "timestamp", "uuid", "version", "agent", "model", "repo", "repo_url",
    "dir", "basename", "branch", "commit", "related", "note",
    "checksum_fields", "checksum",
)


def git(*args, cwd):
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (subprocess.SubprocessError, FileNotFoundError):
        return ""


def validate_repo(name):
    if "/" in name or ".." in name or name.startswith("."):
        raise ValueError(f"invalid repo name {name!r}")


def validate_file_rel(file_rel):
    fp = PurePosixPath(file_rel)
    if fp.is_absolute() or any(p == ".." for p in fp.parts) or not fp.name:
        raise ValueError(f"invalid file path {file_rel!r}")
    return fp


@dataclass
class Note:
    timestamp: str
    uuid: str
    agent: str
    model: str
    repo: str
    dir: str
    basename: str
    branch: str
    # `list[str]` from v3.0.0 onward: index 0 is the original anchor, the
    # last element is current, middle entries are intermediate rewrites
    # (rebase / amend). Legacy v2 notes stored a single string; from_dict
    # preserves whichever form is on disk so existing checksums verify.
    commit: list[str] | str
    note: str
    version: str = ""
    repo_url: str = ""
    related: list = field(default_factory=list)
    checksum_fields: list = field(default_factory=list)
    checksum: str = ""

    @classmethod
    def create(cls, *, agent, model, repo, repo_url, file_rel, branch, commit, related, note):
        # file_rel is a PurePosixPath validated by the caller
        parent = str(file_rel.parent)
        dir_in_repo = "" if parent == "." else parent
        n = cls(
            timestamp=datetime.now(timezone.utc).isoformat(),
            uuid=str(uuidlib.uuid4()),
            version=SCHEMA_VERSION,
            agent=agent,
            model=model,
            repo=repo,
            repo_url=repo_url or "",
            dir=dir_in_repo,
            basename=file_rel.name,
            branch=branch,
            commit=[commit],
            related=list(related or []),
            note=note,
            checksum_fields=list(CHECKSUM_FIELDS),
        )
        n.checksum = n.compute_checksum()
        return n

    @classmethod
    def from_dict(cls, data):
        return cls(
            timestamp=data.get("timestamp", ""),
            uuid=data.get("uuid", ""),
            version=data.get("version", "") or "",
            agent=data.get("agent", ""),
            model=data.get("model", ""),
            repo=data.get("repo", ""),
            repo_url=data.get("repo_url", "") or "",
            dir=data.get("dir", "") or "",
            basename=data.get("basename", ""),
            branch=data.get("branch", ""),
            commit=data.get("commit", ""),
            related=list(data.get("related") or []),
            note=data.get("note", ""),
            checksum_fields=list(data.get("checksum_fields") or []),
            checksum=data.get("checksum", "") or "",
        )

    def to_dict(self):
        # Insertion order preserved — matches the on-disk layout the corpus
        # was written with originally.
        d = {
            "timestamp": self.timestamp,
            "uuid": self.uuid,
        }
        if self.version:
            d["version"] = self.version
        d["agent"] = self.agent
        d["model"] = self.model
        d["repo"] = self.repo
        if self.repo_url:
            d["repo_url"] = self.repo_url
        d["dir"] = self.dir
        d["basename"] = self.basename
        d["branch"] = self.branch
        d["commit"] = self.commit
        d["related"] = list(self.related)
        d["note"] = self.note
        if self.checksum_fields:
            d["checksum_fields"] = list(self.checksum_fields)
        if self.checksum:
            d["checksum"] = self.checksum
        return d

    def compute_checksum(self):
        payload_dict = {k: getattr(self, k) for k in self.checksum_fields}
        payload = json.dumps(
            payload_dict,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def verify(self):
        """Return 'valid', 'corrupted', or 'no_checksum'.

        An empty `checksum_fields` means the note declares no integrity
        coverage (legacy notes written before the self-describing scheme),
        so verification is skipped and reported as 'no_checksum'.
        """
        if not self.checksum_fields or not self.checksum:
            return "no_checksum"
        return "valid" if self.checksum == self.compute_checksum() else "corrupted"

    def location(self):
        d = self.dir or ""
        return f"{self.repo}/" + (f"{d}/" if d else "") + self.basename

    def current_commit(self) -> str:
        """The currently-active short SHA, regardless of on-disk form."""
        if isinstance(self.commit, list):
            return self.commit[-1] if self.commit else ""
        return self.commit

    def append_commit(self, new_sha: str) -> bool:
        """Record a rewrite of the current commit (rebase / amend).

        Promotes legacy string-form `commit` to a list, appends the new
        SHA, bumps `version` to the current schema, and recomputes the
        checksum. No-ops if `new_sha` already equals the current commit
        (idempotent against re-runs of the rewrite hook). Returns True
        if the note changed.
        """
        if not new_sha or new_sha == self.current_commit():
            return False
        if isinstance(self.commit, str):
            self.commit = [self.commit, new_sha] if self.commit else [new_sha]
        else:
            self.commit = [*self.commit, new_sha]
        self.version = SCHEMA_VERSION
        self.checksum = self.compute_checksum()
        return True


class NotesStore:
    """Owns the on-disk corpus rooted at `root`."""

    def __init__(self, root):
        self.root = Path(root)

    @classmethod
    def resolve(cls, cwd):
        """Resolve the corpus root: $WHY_NOTES_DIR, then <git-root>/why-notes, then <cwd>/why-notes."""
        env_dir = os.environ.get("WHY_NOTES_DIR")
        if env_dir:
            return cls(env_dir)
        repo_root = git("rev-parse", "--show-toplevel", cwd=cwd)
        return cls((Path(repo_root) if repo_root else Path(cwd)) / "why-notes")

    def iter_notes(self):
        """Yield (path, Note) for every readable JSON in the corpus."""
        if not self.root.is_dir():
            return
        for f in self.root.rglob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            yield f, Note.from_dict(data)

    def index_by_uuid(self):
        return {n.uuid: (p, n) for p, n in self.iter_notes() if n.uuid}

    def primaries_for(self, repo, file_rel):
        """Return notes anchored exactly to repo + file_rel (PurePosixPath)."""
        parent = str(file_rel.parent)
        target_dir = self.root / repo
        if parent != ".":
            target_dir = target_dir / parent
        if not target_dir.is_dir():
            return []
        expected_dir = "" if parent == "." else parent
        out = []
        for f in target_dir.glob(f"{file_rel.name}-*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if data.get("basename") == file_rel.name and data.get("dir", "") == expected_dir:
                out.append(Note.from_dict(data))
        return out

    def path_for(self, note):
        target_dir = self.root / note.repo
        if note.dir:
            target_dir = target_dir / note.dir
        return target_dir / f"{note.basename}-{note.uuid}.json"

    def write(self, note):
        path = self.path_for(note)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(note.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return path

    def add_backlink(self, rel_uuid, note_uuid):
        """Append note_uuid to rel_uuid's `related` list. Returns the patched path or None.

        `related` is intentionally outside CHECKSUM_FIELDS, so backlinks
        do not invalidate the referenced note's checksum.
        """
        for path, note in self.iter_notes():
            if note.uuid != rel_uuid:
                continue
            if note_uuid not in note.related:
                note.related.append(note_uuid)
                path.write_text(
                    json.dumps(note.to_dict(), indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
            return path
        return None


def reconfigure_streams_utf8(streams):
    for s in streams:
        try:
            s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def validate_uuids(uuids):
    for u in uuids:
        try:
            uuidlib.UUID(u)
        except ValueError:
            raise ValueError(f"invalid uuid {u!r}")
