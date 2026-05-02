"""End-to-end tests for record.py and consult.py via subprocess.

Each test runs the CLI in an isolated temp git repo and points the
corpus at a temp directory via WHY_NOTES_DIR.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
RECORD = SRC / "record.py"
CONSULT = SRC / "consult.py"


def init_git_repo(path):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True, env=env)
    (Path(path) / "seed.txt").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "seed.txt"], cwd=path, check=True, env=env)
    subprocess.run(
        ["git", "commit", "-q", "-m", "seed"], cwd=path, check=True, env=env
    )


def run_record(cwd, notes_dir, *args, stdin="", extra_env=None):
    env = {**os.environ, "WHY_NOTES_DIR": str(notes_dir)}
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(RECORD), *args],
        cwd=cwd,
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
    )


def run_consult(cwd, notes_dir, *args):
    env = {**os.environ, "WHY_NOTES_DIR": str(notes_dir)}
    return subprocess.run(
        [sys.executable, str(CONSULT), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
    )


class RecordCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        self.notes = Path(self.tmp.name) / "notes"
        init_git_repo(self.repo)

    def test_record_writes_note_and_round_trips_through_consult(self):
        r = run_record(
            self.repo, self.notes,
            "--agent", "claude",
            "--model", "opus 4.7",
            "--repo", "demo",
            "--file", "src/foo.py",
            stdin="because we needed to",
        )
        self.assertEqual(r.returncode, 0, r.stderr)

        # Exactly one note on disk in the expected location.
        files = list((self.notes / "demo" / "src").glob("foo.py-*.json"))
        self.assertEqual(len(files), 1)
        data = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(data["agent"], "claude")
        self.assertEqual(data["basename"], "foo.py")
        self.assertEqual(data["dir"], "src")
        self.assertEqual(data["note"], "because we needed to")
        self.assertTrue(data["checksum"])

        c = run_consult(self.repo, self.notes, "--repo", "demo", "--file", "src/foo.py")
        self.assertEqual(c.returncode, 0, c.stderr)
        self.assertIn("because we needed to", c.stdout)
        self.assertIn(data["uuid"], c.stdout)

    def test_record_rejects_empty_stdin(self):
        r = run_record(
            self.repo, self.notes,
            "--agent", "claude", "--model", "opus 4.7",
            "--repo", "demo", "--file", "src/foo.py",
            stdin="   \n",
        )
        self.assertEqual(r.returncode, 1)
        self.assertIn("empty input", r.stderr)

    def test_record_rejects_oversize_non_human_note(self):
        big = "x" * 50
        r = run_record(
            self.repo, self.notes,
            "--agent", "claude", "--model", "opus 4.7",
            "--repo", "demo", "--file", "src/foo.py",
            "--max-chars", "10",
            stdin=big,
        )
        self.assertEqual(r.returncode, 7)
        self.assertIn("exceeds --max-chars", r.stderr)

    def test_record_allows_oversize_human_note(self):
        big = "x" * 50
        r = run_record(
            self.repo, self.notes,
            "--agent", "human", "--model", "Joose",
            "--repo", "demo", "--file", "src/foo.py",
            "--max-chars", "10",
            stdin=big,
        )
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_record_rejects_invalid_repo(self):
        r = run_record(
            self.repo, self.notes,
            "--agent", "claude", "--model", "opus 4.7",
            "--repo", "../escape", "--file", "src/foo.py",
            stdin="x",
        )
        self.assertEqual(r.returncode, 2)

    def test_record_rejects_invalid_file_path(self):
        r = run_record(
            self.repo, self.notes,
            "--agent", "claude", "--model", "opus 4.7",
            "--repo", "demo", "--file", "../escape.py",
            stdin="x",
        )
        self.assertEqual(r.returncode, 4)

    def test_record_rejects_invalid_related_uuid(self):
        r = run_record(
            self.repo, self.notes,
            "--agent", "claude", "--model", "opus 4.7",
            "--repo", "demo", "--file", "src/foo.py",
            "--related", "not-a-uuid",
            stdin="x",
        )
        self.assertEqual(r.returncode, 5)

    def test_record_fails_outside_git_repo(self):
        non_git = Path(self.tmp.name) / "plain"
        non_git.mkdir()
        r = run_record(
            non_git, self.notes,
            "--agent", "claude", "--model", "opus 4.7",
            "--repo", "demo", "--file", "src/foo.py",
            stdin="x",
        )
        self.assertEqual(r.returncode, 3)
        self.assertIn("no git commit", r.stderr)

    def test_record_creates_backlink_for_related(self):
        # First note is the target.
        r1 = run_record(
            self.repo, self.notes,
            "--agent", "claude", "--model", "opus 4.7",
            "--repo", "demo", "--file", "src/a.py",
            stdin="first",
        )
        self.assertEqual(r1.returncode, 0, r1.stderr)
        target_path = next((self.notes / "demo" / "src").glob("a.py-*.json"))
        target_uuid = json.loads(target_path.read_text(encoding="utf-8"))["uuid"]

        # Second note links to it.
        r2 = run_record(
            self.repo, self.notes,
            "--agent", "claude", "--model", "opus 4.7",
            "--repo", "demo", "--file", "src/b.py",
            "--related", target_uuid,
            stdin="second",
        )
        self.assertEqual(r2.returncode, 0, r2.stderr)
        new_uuid = json.loads(
            next((self.notes / "demo" / "src").glob("b.py-*.json")).read_text(
                encoding="utf-8"
            )
        )["uuid"]

        patched = json.loads(target_path.read_text(encoding="utf-8"))
        self.assertIn(new_uuid, patched["related"])

    def test_record_warns_on_unknown_related_uuid(self):
        unknown = "11111111-1111-1111-1111-111111111111"
        r = run_record(
            self.repo, self.notes,
            "--agent", "claude", "--model", "opus 4.7",
            "--repo", "demo", "--file", "src/foo.py",
            "--related", unknown,
            stdin="x",
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("not found", r.stderr)


class ConsultCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        self.notes = Path(self.tmp.name) / "notes"
        init_git_repo(self.repo)

    def test_consult_with_no_notes_dir_returns_zero_with_message(self):
        r = run_consult(
            self.repo, self.notes, "--repo", "demo", "--file", "src/foo.py"
        )
        self.assertEqual(r.returncode, 0)
        self.assertIn("no notes", r.stderr)

    def test_consult_flags_tampered_note(self):
        r = run_record(
            self.repo, self.notes,
            "--agent", "claude", "--model", "opus 4.7",
            "--repo", "demo", "--file", "src/foo.py",
            stdin="original",
        )
        self.assertEqual(r.returncode, 0, r.stderr)

        path = next((self.notes / "demo" / "src").glob("foo.py-*.json"))
        data = json.loads(path.read_text(encoding="utf-8"))
        data["note"] = "edited after the fact"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        c = run_consult(
            self.repo, self.notes, "--repo", "demo", "--file", "src/foo.py"
        )
        self.assertEqual(c.returncode, 0, c.stderr)
        self.assertIn("failed checksum", c.stderr)

    def test_consult_follows_related_cross_references(self):
        # Note A.
        r1 = run_record(
            self.repo, self.notes,
            "--agent", "claude", "--model", "opus 4.7",
            "--repo", "demo", "--file", "src/a.py",
            stdin="rationale A",
        )
        self.assertEqual(r1.returncode, 0, r1.stderr)
        a_uuid = json.loads(
            next((self.notes / "demo" / "src").glob("a.py-*.json")).read_text(
                encoding="utf-8"
            )
        )["uuid"]

        # Note B links to A.
        r2 = run_record(
            self.repo, self.notes,
            "--agent", "claude", "--model", "opus 4.7",
            "--repo", "demo", "--file", "src/b.py",
            "--related", a_uuid,
            stdin="rationale B references A",
        )
        self.assertEqual(r2.returncode, 0, r2.stderr)

        # Consulting B should surface A as a related note.
        c = run_consult(
            self.repo, self.notes, "--repo", "demo", "--file", "src/b.py"
        )
        self.assertEqual(c.returncode, 0, c.stderr)
        self.assertIn("rationale B references A", c.stdout)
        self.assertIn("rationale A", c.stdout)
        self.assertIn("Related notes", c.stdout)

    def test_consult_rejects_invalid_repo(self):
        c = run_consult(
            self.repo, self.notes, "--repo", "../escape", "--file", "src/foo.py"
        )
        self.assertEqual(c.returncode, 2)


if __name__ == "__main__":
    unittest.main()
