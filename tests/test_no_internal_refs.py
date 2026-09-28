"""Private work-item references must not appear in this (public) repo's files.

Several test docstrings used to cite the internal work item they were written
for. Those references are private, so they were removed and the sentences kept:
the prose says what a test binds and why, and it reads fine without the row
name.

This guard stops them coming back. It cannot list the references in plain text
(that would publish them again), so it holds their SHA-256 digests and hashes
every reference-shaped token in every tracked file. A shape-only scan is not
usable here: ordinary hyphenated words like `font-family`, `max-height` and
`re-enroll` have the same shape, so only a digest match counts as a hit.

Known limit: a denylist catches a RETURN of a reference it already knows, never
the arrival of a new one.
"""

import hashlib
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# A hyphen may stand on either side of a reference ("post-<ref>" is a real
# occurrence this repo had), so the lookarounds exclude alphanumerics ONLY. A
# lookbehind that also excluded "-" reads that occurrence as clean.
TOKEN = re.compile(r"(?<![A-Za-z0-9])[a-z]{2,4}-[0-9a-z]{6}(?![A-Za-z0-9])")

DENYLIST = frozenset(
    {
        "fa66f4119f4ea8fec2eeada85e10aaa4e6787e077273df56a88c3c86d081f5f6",
        "fa7c1a060468b060a78103bcd0235523a7a00cd2a6138278c819631f82b84a70",
        "6f76598948b652c617f1a1c4a1902816dfc8b0fc3f0be9ed85ac652eff1b842f",
        "68ae1c533f7a4cc7dbd23b1400adf17ba42fae3b2418b7d9d3e12dc51ce898b5",
        "495ed738c2741e624e6af9b16532c09ddc3a998a708a3c3fa3cf811fefdba220",
        "b25c4f5f0c8153862b3237133ce907947b6a939b13438a793e0f5797b8848610",
        "d2e1e703b5c84eb4b29f0e2d5475121dda108fcb6a510942af4357f4904eb6d5",
    }
)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def denylisted_tokens(text: str, denylist=DENYLIST) -> list[str]:
    """Every token in `text` whose digest is on `denylist`, in order."""
    return [t for t in TOKEN.findall(text) if _digest(t) in denylist]


def _tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO,
        check=True,
        capture_output=True,
    ).stdout
    return [REPO / p for p in out.decode().split("\0") if p]


# --- the scanner can say YES and NO --------------------------------------
# A synthetic reference stands in for a real one, so these arms can be read
# without publishing anything.

SYNTHETIC = "zz-q9q9q9"
SYNTHETIC_LIST = frozenset({_digest(SYNTHETIC)})


@pytest.mark.parametrize(
    "text",
    [
        f"docstring citing it (see {SYNTHETIC}).",
        f"and post-{SYNTHETIC}, an empty set",  # hyphen before
        f"{SYNTHETIC}-harness/run.sh",  # hyphen after
    ],
)
def test_scanner_finds_a_denylisted_reference(text):
    assert denylisted_tokens(text, SYNTHETIC_LIST) == [SYNTHETIC]


@pytest.mark.parametrize(
    "text",
    [
        "font-family: sans; max-height: 10px; re-enroll",  # same shape, not listed
        f"x{SYNTHETIC}",  # alnum run before: a different token
        f"{SYNTHETIC}0",  # alnum run after: a different token
        "",
    ],
)
def test_scanner_ignores_everything_else(text):
    assert denylisted_tokens(text, SYNTHETIC_LIST) == []


# --- the repo itself ------------------------------------------------------


def test_tracked_files_are_scanned():
    """Anti-vacuity: a scan over zero files, or one that never matches a
    reference-shaped token, passes the real check for free."""
    files = _tracked_files()
    assert len(files) > 10
    shaped = sum(
        len(TOKEN.findall(f.read_text(errors="replace"))) for f in files if f.is_file()
    )
    assert shaped > 0


def test_no_tracked_file_carries_a_private_reference():
    hits = []
    for f in _tracked_files():
        if not f.is_file():
            continue
        text = f.read_text(errors="replace")
        for n, line in enumerate(text.splitlines(), 1):
            if denylisted_tokens(line):
                # Name the location, never the token.
                hits.append(f"{f.relative_to(REPO)}:{n}")
    assert hits == [], f"private reference at: {hits}"
