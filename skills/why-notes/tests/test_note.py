"""Unit tests for the why-notes data model in src/note.py."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path, PurePosixPath
from unittest import mock

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from note import (  # noqa: E402
    CHECKSUM_FIELDS,
    CHECKSUM_FIELDS_OPTIONAL,
    SCHEMA_VERSION,
    Note,
    NotesStore,
    validate_file_rel,
    validate_repo,
    validate_uuids,
)


def make_note(**overrides):
    defaults = dict(
        agent="claude",
        model="opus 4.7",
        repo="why-notes",
        repo_url="https://example.com/repo",
        file_rel=PurePosixPath("src/note.py"),
        branch="main",
        commit="abc1234",
        related=[],
        note="some rationale",
    )
    defaults.update(overrides)
    return Note.create(**defaults)


class ValidatorTests(unittest.TestCase):
    def test_validate_repo_rejects_separators_and_traversal(self):
        for bad in ("a/b", "..", ".hidden", "x/../y"):
            with self.assertRaises(ValueError):
                validate_repo(bad)

    def test_validate_repo_accepts_plain_name(self):
        validate_repo("why-notes")  # no exception

    def test_validate_file_rel_rejects_absolute_and_traversal(self):
        for bad in ("/etc/passwd", "../escape.py", "a/../b.py", ""):
            with self.assertRaises(ValueError):
                validate_file_rel(bad)

    def test_validate_file_rel_returns_pureposixpath(self):
        p = validate_file_rel("src/auth/login.py")
        self.assertIsInstance(p, PurePosixPath)
        self.assertEqual(p.name, "login.py")
        self.assertEqual(str(p.parent), "src/auth")

    def test_validate_uuids_rejects_garbage(self):
        with self.assertRaises(ValueError):
            validate_uuids(["not-a-uuid"])

    def test_validate_uuids_accepts_valid(self):
        validate_uuids(["12345678-1234-5678-1234-567812345678"])  # no exception


class NoteChecksumTests(unittest.TestCase):
    def test_create_populates_checksum_and_verifies(self):
        n = make_note()
        self.assertTrue(n.checksum)
        self.assertEqual(n.verify(), "valid")

    def test_checksum_includes_version_when_present(self):
        # Hand-build a legacy note with no version, checksum'd over base fields.
        legacy = make_note()
        legacy.version = ""
        legacy.checksum = legacy.compute_checksum()
        self.assertEqual(legacy.verify(), "valid")
        # Same fields but with version set should produce a *different* checksum.
        modern = make_note()
        modern.version = SCHEMA_VERSION
        modern.checksum = modern.compute_checksum()
        self.assertNotEqual(legacy.checksum, modern.checksum)

    def test_legacy_note_without_version_still_verifies(self):
        # Simulate a note saved before the version field existed.
        n = make_note()
        n.version = ""
        n.checksum = n.compute_checksum()
        # Round-trip through dict to mimic on-disk read.
        round_tripped = Note.from_dict(n.to_dict())
        self.assertEqual(round_tripped.verify(), "valid")

    def test_tampered_note_flagged(self):
        n = make_note()
        n.note = "edited after recording"
        self.assertEqual(n.verify(), "tampered")

    def test_no_checksum_returns_no_checksum(self):
        n = make_note()
        n.checksum = ""
        self.assertEqual(n.verify(), "no_checksum")

    def test_related_field_excluded_from_checksum(self):
        # Backlinks must not invalidate the referenced note's checksum.
        n = make_note()
        original = n.checksum
        n.related.append("11111111-1111-1111-1111-111111111111")
        self.assertEqual(n.verify(), "valid")
        self.assertEqual(n.compute_checksum(), original)

    def test_checksum_field_lists_have_no_overlap(self):
        self.assertEqual(set(CHECKSUM_FIELDS) & set(CHECKSUM_FIELDS_OPTIONAL), set())


class NoteSerializationTests(unittest.TestCase):
    def test_to_dict_round_trip(self):
        n = make_note(related=["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"])
        d = n.to_dict()
        n2 = Note.from_dict(d)
        self.assertEqual(n2.to_dict(), d)
        self.assertEqual(n2.verify(), "valid")

    def test_to_dict_omits_empty_optional_fields(self):
        n = make_note()
        n.repo_url = ""
        n.version = ""
        n.checksum = ""
        d = n.to_dict()
        self.assertNotIn("repo_url", d)
        self.assertNotIn("version", d)
        self.assertNotIn("checksum", d)

    def test_dir_empty_when_file_at_repo_root(self):
        n = make_note(file_rel=PurePosixPath("README.md"))
        self.assertEqual(n.dir, "")
        self.assertEqual(n.basename, "README.md")

    def test_location_format(self):
        n = make_note()
        self.assertEqual(n.location(), "why-notes/src/note.py")
        flat = make_note(file_rel=PurePosixPath("README.md"))
        self.assertEqual(flat.location(), "why-notes/README.md")


class NotesStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = NotesStore(self.tmp.name)

    def test_path_for_includes_dir(self):
        n = make_note()
        p = self.store.path_for(n)
        expected = (
            Path(self.tmp.name) / "why-notes" / "src" / f"note.py-{n.uuid}.json"
        )
        self.assertEqual(p, expected)

    def test_path_for_root_file(self):
        n = make_note(file_rel=PurePosixPath("README.md"))
        p = self.store.path_for(n)
        expected = Path(self.tmp.name) / "why-notes" / f"README.md-{n.uuid}.json"
        self.assertEqual(p, expected)

    def test_write_creates_parent_dirs(self):
        n = make_note()
        p = self.store.write(n)
        self.assertTrue(p.is_file())
        loaded = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(loaded["uuid"], n.uuid)

    def test_primaries_for_returns_only_matching_file(self):
        n1 = make_note(file_rel=PurePosixPath("src/note.py"))
        n2 = make_note(file_rel=PurePosixPath("src/note.py"))
        other = make_note(file_rel=PurePosixPath("src/record.py"))
        self.store.write(n1)
        self.store.write(n2)
        self.store.write(other)
        got = self.store.primaries_for("why-notes", PurePosixPath("src/note.py"))
        uuids = {n.uuid for n in got}
        self.assertEqual(uuids, {n1.uuid, n2.uuid})

    def test_primaries_for_root_file(self):
        n = make_note(file_rel=PurePosixPath("README.md"))
        self.store.write(n)
        got = self.store.primaries_for("why-notes", PurePosixPath("README.md"))
        self.assertEqual([m.uuid for m in got], [n.uuid])

    def test_primaries_for_missing_dir_returns_empty(self):
        self.assertEqual(
            self.store.primaries_for("nonexistent", PurePosixPath("x.py")),
            [],
        )

    def test_iter_notes_skips_invalid_json(self):
        n = make_note()
        self.store.write(n)
        # Drop a malformed file that matches *.json.
        bad = Path(self.tmp.name) / "why-notes" / "src" / "garbage.json"
        bad.write_text("{not json", encoding="utf-8")
        uuids = [note.uuid for _, note in self.store.iter_notes()]
        self.assertIn(n.uuid, uuids)

    def test_index_by_uuid(self):
        n = make_note()
        self.store.write(n)
        idx = self.store.index_by_uuid()
        self.assertIn(n.uuid, idx)
        _, found = idx[n.uuid]
        self.assertEqual(found.uuid, n.uuid)

    def test_add_backlink_appends_uuid(self):
        target = make_note()
        self.store.write(target)
        new_uuid = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        patched = self.store.add_backlink(target.uuid, new_uuid)
        self.assertIsNotNone(patched)
        loaded = json.loads(patched.read_text(encoding="utf-8"))
        self.assertIn(new_uuid, loaded["related"])

    def test_add_backlink_idempotent(self):
        target = make_note()
        self.store.write(target)
        u = "cccccccc-cccc-cccc-cccc-cccccccccccc"
        self.store.add_backlink(target.uuid, u)
        self.store.add_backlink(target.uuid, u)
        loaded = json.loads(self.store.path_for(target).read_text(encoding="utf-8"))
        self.assertEqual(loaded["related"].count(u), 1)

    def test_add_backlink_preserves_target_checksum(self):
        target = make_note()
        original_checksum = target.checksum
        self.store.write(target)
        self.store.add_backlink(
            target.uuid, "dddddddd-dddd-dddd-dddd-dddddddddddd"
        )
        loaded = json.loads(self.store.path_for(target).read_text(encoding="utf-8"))
        self.assertEqual(loaded["checksum"], original_checksum)
        # And the loaded note still verifies.
        self.assertEqual(Note.from_dict(loaded).verify(), "valid")

    def test_add_backlink_missing_target_returns_none(self):
        result = self.store.add_backlink(
            "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
            "ffffffff-ffff-ffff-ffff-ffffffffffff",
        )
        self.assertIsNone(result)


class NotesStoreResolveTests(unittest.TestCase):
    def test_env_var_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"WHY_NOTES_DIR": tmp}):
                store = NotesStore.resolve(cwd="/does/not/matter")
                self.assertEqual(store.root, Path(tmp))

    def test_falls_back_to_git_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {k: v for k, v in os.environ.items() if k != "WHY_NOTES_DIR"}
            with mock.patch.dict(os.environ, env, clear=True):
                with mock.patch("note.git", return_value=tmp):
                    store = NotesStore.resolve(cwd=tmp)
                    self.assertEqual(store.root, Path(tmp) / "why-notes")

    def test_falls_back_to_cwd_when_no_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {k: v for k, v in os.environ.items() if k != "WHY_NOTES_DIR"}
            with mock.patch.dict(os.environ, env, clear=True):
                with mock.patch("note.git", return_value=""):
                    store = NotesStore.resolve(cwd=tmp)
                    self.assertEqual(store.root, Path(tmp) / "why-notes")


if __name__ == "__main__":
    unittest.main()
