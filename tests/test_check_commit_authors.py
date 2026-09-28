"""sys/check-commit-authors.sh: the CI gate over commit authorship.

A gate like this is easy to land inert: main is clean on the author axis, so a
green run over it proves nothing. Every arm here runs the SHIPPED script against
a throwaway repo that holds the defect (a commit authored by a tool identity),
and the bad-author arm is the positive control that shows the script can fail.

The arm that earns its keep is the zero-scan one. A range that RESOLVES but
holds no non-merge commits used to print "All commits ... authored by Adam" at
exit 0, which reads the same as a real pass. It must print the count, and with
--require-commits (which the workflow passes) it must refuse with exit 3.

The last section binds the workflow call site, because every other arm drives
the script directly and would stay green against a workflow that stopped
calling it.
"""

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
GATE = REPO / "sys" / "check-commit-authors.sh"
HOOK = REPO / ".githooks" / "pre-commit"
WORKFLOW = REPO / ".github" / "workflows" / "test.yml"

GOOD = ("Adam Setapen", "asetapen@gmail.com")
BAD = ("some-bot", "some-bot@example.invalid")
ZERO_SHA = "0" * 40


def _env(author=None):
    """A clean env: the caller's shell may export GIT_AUTHOR_* (that is the
    very failure mode under test), and env beats config."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["HOME"] = os.environ.get("HOME", "/tmp")
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    if author:
        env["GIT_AUTHOR_NAME"], env["GIT_AUTHOR_EMAIL"] = author
    return env


def _git(repo, *args, author=None):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=_env(author),
    ).stdout.strip()


def _commit(repo, name, author=GOOD):
    (repo / name).write_text(name)
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", name, author=author)
    return _git(repo, "rev-parse", "HEAD")


def _run(repo, *args, author=None):
    return subprocess.run(
        ["bash", str(GATE), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        env=_env(author),
    )


@pytest.fixture
def repo(tmp_path):
    """base (good) -> good -> bad, plus a side branch whose only new commit
    is a merge, so `base..merge-only` resolves and scans zero."""
    r = tmp_path / "r"
    r.mkdir()
    _git(r, "init", "-q", "--template=")
    _git(r, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(r, "config", "user.name", GOOD[0])
    _git(r, "config", "user.email", GOOD[1])
    _git(r, "config", "commit.gpgsign", "false")
    base = _commit(r, "base")
    # A merge-only range: side gets one commit S, merge-only merges it into
    # base with --no-ff, and S..merge-only then holds the merge commit alone.
    _git(r, "checkout", "-q", "-b", "side")
    side = _commit(r, "side")
    _git(r, "checkout", "-q", "-b", "merge-only", base)
    _git(r, "merge", "-q", "--no-ff", "-m", "merge", "side", author=GOOD)
    _git(r, "checkout", "-q", "main")
    good = _commit(r, "good")
    bad = _commit(r, "bad", author=BAD)
    # Assert the fixture holds the phenomenon, read through git log rather
    # than through the script under test.
    authors = _git(r, "log", "--format=%an", f"{base}..{bad}").splitlines()
    assert authors == [BAD[0], GOOD[0]]
    zero = f"{side}..merge-only"
    assert _git(r, "rev-list", "--count", "--no-merges", zero) == "0"
    assert _git(r, "rev-list", "--count", zero) == "1"
    return {"path": r, "base": base, "good": good, "bad": bad, "zero": zero}


# --- the range check ---------------------------------------------------------


def test_bad_author_is_refused_and_named(repo):
    """Positive control: the script can fail."""
    res = _run(repo["path"], f"{repo['base']}..{repo['bad']}")
    assert res.returncode == 1
    assert f"BAD AUTHOR {repo['bad']}" in res.stderr
    assert "1 of 2 commit(s)" in res.stderr


def test_good_range_passes_with_its_count(repo):
    res = _run(repo["path"], f"{repo['base']}..{repo['good']}")
    assert res.returncode == 0, res.stderr
    assert "All 1 commit(s)" in res.stdout


def test_zero_scan_without_flag_says_zero_not_all(repo):
    res = _run(repo["path"], repo["zero"])
    assert res.returncode == 0, res.stderr
    assert "0 scanned" in res.stdout
    assert "authored by" not in res.stdout


def test_zero_scan_with_require_commits_is_refused(repo):
    res = _run(repo["path"], "--require-commits", repo["zero"])
    assert res.returncode == 3
    assert "scanned 0 commits" in res.stderr


def test_require_commits_still_passes_a_real_range(repo):
    """The refusal is not a constant no."""
    res = _run(repo["path"], "--require-commits", f"{repo['base']}..{repo['good']}")
    assert res.returncode == 0, res.stderr


def test_require_commits_still_refuses_a_bad_author(repo):
    res = _run(repo["path"], "--require-commits", f"{repo['base']}..{repo['bad']}")
    assert res.returncode == 1


def test_unresolvable_range_is_refused(repo):
    res = _run(repo["path"], "nosuchref..HEAD")
    assert res.returncode == 2
    assert "cannot resolve range" in res.stderr


# --- the event-range arm -----------------------------------------------------


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["main", "b" * 40, "c" * 40], "origin/main..HEAD"),  # pull_request
        (["", "b" * 40, "c" * 40], f"{'b' * 40}..{'c' * 40}"),  # push
        (["", ZERO_SHA, "c" * 40], f"{'c' * 40}~1..{'c' * 40}"),  # first push
    ],
)
def test_event_range(repo, args, expected):
    res = _run(repo["path"], "--event-range", *args)
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == expected


@pytest.mark.parametrize(
    "args",
    [
        ["main", "b" * 40, ""],  # no sha
        ["", "", "c" * 40],  # push with no before
    ],
)
def test_event_range_refuses_empty_inputs(repo, args):
    """An unset ${{ }} is empty, and `..<sha>` would resolve to HEAD..<sha>."""
    res = _run(repo["path"], "--event-range", *args)
    assert res.returncode == 2
    assert res.stdout == ""


def test_push_to_main_range_is_not_empty(repo):
    """The push arm must scan what the push moved. The pull_request spelling
    over a push (HEAD is main) would scan nothing."""
    r = repo["path"]
    rng = _run(r, "--event-range", "", repo["base"], repo["good"]).stdout.strip()
    res = _run(r, "--require-commits", rng)
    assert res.returncode == 0, res.stderr
    assert "All 1 commit(s)" in res.stdout


# --- the pre-commit hook arm -------------------------------------------------


def test_identity_accepts_adam(repo):
    assert _run(repo["path"], "--identity", author=GOOD).returncode == 0


def test_identity_refuses_an_env_override(repo):
    """The env beats a correct git config: this is the failure mode itself."""
    res = _run(repo["path"], "--identity", author=BAD)
    assert res.returncode == 1
    assert BAD[0] in res.stderr


def test_hook_blocks_a_bad_commit(repo):
    r = repo["path"]
    _git(r, "config", "core.hooksPath", str(HOOK.parent))
    # The hook resolves the gate relative to the repo it runs in.
    (r / "sys").mkdir()
    (r / "sys" / GATE.name).write_bytes(GATE.read_bytes())
    (r / "sys" / GATE.name).chmod(0o755)
    (r / "x").write_text("x")
    _git(r, "add", "x")
    before = _git(r, "rev-parse", "HEAD")
    blocked = subprocess.run(
        ["git", "-C", str(r), "commit", "-q", "-m", "x"],
        capture_output=True,
        text=True,
        env=_env(BAD),
    )
    assert blocked.returncode != 0
    assert _git(r, "rev-parse", "HEAD") == before  # nothing landed
    allowed = subprocess.run(
        ["git", "-C", str(r), "commit", "-q", "-m", "x"],
        capture_output=True,
        text=True,
        env=_env(GOOD),
    )
    assert allowed.returncode == 0, allowed.stderr


# --- the workflow call site --------------------------------------------------


def _job_lines(name):
    """The job's non-comment lines, so prose cannot satisfy a check."""
    text = WORKFLOW.read_text()
    m = re.search(rf"^  {name}:\n(.*?)(?=^  \S|\Z)", text, re.S | re.M)
    assert m, f"no {name} job"
    return [ln for ln in m.group(1).splitlines() if not ln.strip().startswith("#")]


def test_workflow_calls_the_gate_with_require_commits():
    code = "\n".join(_job_lines("commit-authors"))
    assert "./sys/check-commit-authors.sh --event-range" in code
    assert "./sys/check-commit-authors.sh --require-commits" in code
    assert "fetch-depth: 0" in code
