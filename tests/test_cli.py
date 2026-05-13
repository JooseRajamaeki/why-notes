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
SRC = ROOT / "skills" / "why-notes" / "src"
RECORD = SRC / "record.py"
CONSULT = SRC / "consult.py"
REWRITE = SRC / "rewrite.py"
HOOK = ROOT / ".githooks" / "post-rewrite"


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


def run_rewrite(cwd, notes_dir, *args, stdin=""):
    env = {**os.environ, "WHY_NOTES_DIR": str(notes_dir)}
    return subprocess.run(
        [sys.executable, str(REWRITE), *args],
        cwd=cwd,
        input=stdin,
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

    def test_consult_flags_corrupted_note(self):
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


class RewriteCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        self.notes = Path(self.tmp.name) / "notes"
        init_git_repo(self.repo)

    def _record_one(self):
        r = run_record(
            self.repo, self.notes,
            "--agent", "claude", "--model", "opus 4.7",
            "--repo", "demo", "--file", "src/foo.py",
            stdin="original rationale",
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        path = next((self.notes / "demo" / "src").glob("foo.py-*.json"))
        return path, json.loads(path.read_text(encoding="utf-8"))

    def test_map_appends_new_sha_and_recomputes_checksum(self):
        path, before = self._record_one()
        old_short = before["commit"][0] if isinstance(before["commit"], list) else before["commit"]
        # Make a second commit so we have a distinct SHA to rewrite TO; without
        # it `new_full` would still resolve to the note's anchor and
        # append_commit (idempotent) would correctly no-op.
        (self.repo / "second.txt").write_text("x\n", encoding="utf-8")
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.com",
        }
        subprocess.run(["git", "add", "second.txt"], cwd=self.repo, check=True, env=env)
        subprocess.run(["git", "commit", "-q", "-m", "second"], cwd=self.repo, check=True, env=env)
        new_full = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.repo,
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        r = run_rewrite(
            self.repo, self.notes,
            "--map", f"{old_short}={new_full}",
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        after = json.loads(path.read_text(encoding="utf-8"))
        self.assertIsInstance(after["commit"], list)
        self.assertEqual(after["commit"][0], old_short)
        self.assertEqual(len(after["commit"]), 2)
        self.assertNotEqual(after["checksum"], before["checksum"])

        # Re-verifies via consult.
        c = run_consult(self.repo, self.notes, "--repo", "demo", "--file", "src/foo.py")
        self.assertEqual(c.returncode, 0, c.stderr)
        self.assertNotIn("failed checksum", c.stderr)

    def test_stdin_skips_pairs_with_no_matching_note(self):
        path, before = self._record_one()
        r = run_rewrite(
            self.repo, self.notes,
            "--stdin",
            stdin="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa "
                  "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n",
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        after = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(after["commit"], before["commit"])
        self.assertEqual(after["checksum"], before["checksum"])

    def test_stdin_handles_empty_input(self):
        r = run_rewrite(self.repo, self.notes, "--stdin", stdin="")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_idempotent_against_repeat_invocations(self):
        path, _ = self._record_one()
        (self.repo / "second.txt").write_text("x\n", encoding="utf-8")
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.com",
        }
        subprocess.run(["git", "add", "second.txt"], cwd=self.repo, check=True, env=env)
        subprocess.run(["git", "commit", "-q", "-m", "second"], cwd=self.repo, check=True, env=env)
        new_full = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.repo,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        old_short = json.loads(path.read_text(encoding="utf-8"))["commit"]
        if isinstance(old_short, list):
            old_short = old_short[0]
        run_rewrite(self.repo, self.notes, "--map", f"{old_short}={new_full}")
        after_first = json.loads(path.read_text(encoding="utf-8"))

        # Second invocation with the same pair: current SHA already equals
        # the abbreviated new SHA, so append_commit no-ops.
        new_short = after_first["commit"][-1]
        run_rewrite(self.repo, self.notes, "--map", f"{new_short}={new_full}")
        after_second = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(after_first, after_second)


class BundledHookTests(unittest.TestCase):
    def test_bundled_hook_is_executable_and_invokes_rewrite(self):
        self.assertTrue(HOOK.is_file(), f"bundled hook missing: {HOOK}")
        self.assertTrue(os.access(HOOK, os.X_OK), f"bundled hook not executable: {HOOK}")
        body = HOOK.read_text(encoding="utf-8")
        # Must end with executing rewrite.py from the repo's installed skill.
        self.assertIn("skills/why-notes/src/rewrite.py", body)
        self.assertIn("--stdin", body)


class PostRewriteHookTests(unittest.TestCase):
    """End-to-end: a real rebase fires .githooks/post-rewrite, which
    pipes git's mapping into rewrite.py and patches matching notes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        self.notes = Path(self.tmp.name) / "notes"

        # A repo with 3 commits we can rebase. Hook is wired via
        # core.hooksPath to the bundled .githooks dir from this checkout.
        self.git_env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.com",
            "WHY_NOTES_DIR": str(self.notes),
            "GIT_SEQUENCE_EDITOR": "true",  # accept the rebase todo as-is
        }
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.repo, check=True, env=self.git_env)
        # Bundled hook resolves `$REPO_ROOT/skills/why-notes/src/rewrite.py`,
        # which only exists when the user's repo has the skill installed
        # alongside the notes (the why-notes repo's own setup). The temp repo
        # doesn't, so write a test-only hook that invokes rewrite.py from this
        # checkout's source tree directly.
        hooks_dir = Path(self.tmp.name) / "hooks"
        hooks_dir.mkdir()
        hook = hooks_dir / "post-rewrite"
        hook.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            f"exec {sys.executable} {REWRITE} --stdin\n",
            encoding="utf-8",
        )
        hook.chmod(0o755)
        subprocess.run(["git", "config", "core.hooksPath", str(hooks_dir)],
                       cwd=self.repo, check=True, env=self.git_env)
        for i in range(3):
            f = self.repo / f"f{i}.txt"
            f.write_text(f"{i}\n", encoding="utf-8")
            subprocess.run(["git", "add", f.name], cwd=self.repo, check=True, env=self.git_env)
            subprocess.run(["git", "commit", "-q", "-m", f"c{i}"], cwd=self.repo,
                           check=True, env=self.git_env)

    def test_amend_propagates_to_note(self):
        r = run_record(
            self.repo, self.notes,
            "--agent", "claude", "--model", "opus 4.7",
            "--repo", "demo", "--file", "src/foo.py",
            stdin="anchor",
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        path = next((self.notes / "demo" / "src").glob("foo.py-*.json"))
        before = json.loads(path.read_text(encoding="utf-8"))
        old_short = before["commit"][0] if isinstance(before["commit"], list) else before["commit"]

        # Amend HEAD with a new message to guarantee a different SHA
        # (--no-edit + same-second timestamp can otherwise reproduce the
        # original SHA and the post-rewrite pair becomes an identity).
        subprocess.run(
            ["git", "commit", "--amend", "-q", "-m", "c2-reworded"],
            cwd=self.repo, check=True, env=self.git_env,
        )
        after = json.loads(path.read_text(encoding="utf-8"))
        self.assertIsInstance(after["commit"], list)
        self.assertEqual(after["commit"][0], old_short)
        self.assertEqual(len(after["commit"]), 2)

        # And the note still verifies via consult.
        c = run_consult(self.repo, self.notes, "--repo", "demo", "--file", "src/foo.py")
        self.assertEqual(c.returncode, 0, c.stderr)
        self.assertNotIn("failed checksum", c.stderr)


if __name__ == "__main__":
    unittest.main()
