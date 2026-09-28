#!/usr/bin/env bash
# Fail if a commit was authored by something other than Adam.
#
# Usage:
#   sys/check-commit-authors.sh [--require-commits] [<range>]   (default range: origin/main..HEAD)
#   sys/check-commit-authors.sh --event-range <base_ref> <before> <sha>
#   sys/check-commit-authors.sh --identity                      (the pre-commit hook arm)
#
# Exit: 0 clean | 1 a commit is not authored by Adam (each is named) | 2 the
# range or the arguments could not be used | 3 the range scanned ZERO commits,
# under --require-commits.
#
# WHY. Automated tools commit to this repo on his behalf, and a misconfigured
# shell silently stamps its own identity instead (GIT_AUTHOR_NAME in the
# environment overrides git config, so nothing errors and the push succeeds).
# That is how c85097c reached a feature branch authored by a tool identity.
# Once such a commit merges, the authorship is permanent.
#
# Scans a RANGE, not all of history, because the two
# adam.setapen@remedyrobotics.com commits predate this repo's conventions and
# are already ancestors of main. Only new work is held to the rule. It reads
# %an/%ae ONLY: the committer is legitimately a tool identity on tool-made
# commits, and rewriting that is not the goal.
#
# This file is kept in step with the same check in Adam's homebase repo
# (resources/check-commit-authors.sh). Change both, or neither.
set -euo pipefail

expected_name="Adam Setapen"
expected_email="asetapen@gmail.com"
zero_sha="0000000000000000000000000000000000000000"

# --- the pre-commit hook arm -------------------------------------------------
# `git var GIT_AUTHOR_IDENT` resolves env-over-config exactly as the commit
# will, so it reads the mechanism above and not the configuration. Feedback
# only: a hook is per-clone, is opt-in (see .githooks/pre-commit), and
# --no-verify skips it. The CI job is the enforcement.
if [ "${1:-}" = "--identity" ]; then
    ident="$(git var GIT_AUTHOR_IDENT)"
    if [ "${ident#"${expected_name} <${expected_email}>"}" != "${ident}" ]; then
        exit 0
    fi
    printf 'This commit would be authored %s, not %s <%s>.\n' \
        "${ident% * *}" "${expected_name}" "${expected_email}" >&2
    printf 'Unset GIT_AUTHOR_NAME/GIT_AUTHOR_EMAIL, or pass the four identity vars.\n' >&2
    exit 1
fi

# --- the event-range arm -----------------------------------------------------
# Computed here rather than in the workflow's `run:` block, so it can be tested.
#
# On pull_request, scan the PR's commits: origin/<base_ref>..HEAD. On a push to
# main, HEAD *is* origin/main, so that same range is empty and the job would be
# a permanent silent no-op on exactly the branch that matters; use
# before..after there instead. github.event.before is all-zeroes on a branch's
# first push, which resolves to nothing, so fall back to the single commit.
# KNOWN NARROWING: that fallback inspects only the tip, so a bad author deeper
# in a first push is not caught. The pull_request arm is the one that gates
# merges, and it scans the whole PR.
if [ "${1:-}" = "--event-range" ]; then
    shift
    base_ref="${1:-}" before="${2:-}" sha="${3:-}"
    # An unset ${{ }} expression is EMPTY, and `..<sha>` means HEAD..<sha> to
    # git: it resolves, it scans, it answers a different question. Refuse
    # rather than emit a plausible range.
    if [ -z "${sha}" ]; then
        printf 'ERROR: --event-range needs a non-empty <sha>.\n' >&2; exit 2
    fi
    if [ -n "${base_ref}" ]; then printf 'origin/%s..HEAD\n' "${base_ref}"
    elif [ -z "${before}" ]; then
        printf 'ERROR: --event-range with no <base_ref> needs a non-empty <before>.\n' >&2; exit 2
    elif [ "${before}" = "${zero_sha}" ]; then printf '%s~1..%s\n' "${sha}" "${sha}"
    else printf '%s..%s\n' "${before}" "${sha}"
    fi
    exit 0
fi

# --- the check ---------------------------------------------------------------
require_commits=0
if [ "${1:-}" = "--require-commits" ]; then require_commits=1; shift; fi
range="${1:-origin/main..HEAD}"

# Resolve the range BEFORE scanning it. Unresolvable and clean are otherwise
# the same reading, and actions/checkout clones shallow by default (hence
# fetch-depth: 0 in the workflow).
if ! git rev-list "${range}" >/dev/null 2>&1; then
    printf 'ERROR: cannot resolve range %s (shallow clone, or missing ref?).\n' "${range}" >&2
    printf 'Refusing to report a pass over a range this script cannot read.\n' >&2
    exit 2
fi

# A command substitution, not a process substitution: a subshell's status is
# discarded, so `set -e` would never see a failed `git log` and the loop would
# read zero lines, indistinguishable from a clean range.
log="$(git log --no-merges --format='%H%x09%an%x09%ae' "${range}")"

scanned=0 bad=0
# A here-doc feeds the loop in THIS shell, so the counters survive it.
while IFS="$(printf '\t')" read -r sha name email; do
    [ -n "${sha}" ] || continue
    scanned=$((scanned + 1))
    if [ "${name}" != "${expected_name}" ] || [ "${email}" != "${expected_email}" ]; then
        printf 'BAD AUTHOR %s: %s <%s>\n' "${sha}" "${name}" "${email}" >&2
        bad=$((bad + 1))
    fi
done <<EOF
${log}
EOF

if [ "${bad}" -gt 0 ]; then
    printf '\n%d of %d commit(s) in %s are not authored by %s <%s>.\n' \
        "${bad}" "${scanned}" "${range}" "${expected_name}" "${expected_email}" >&2
    printf 'Rebase amending the author, or squash-merge so the merge commit carries it.\n' >&2
    exit 1
fi

# ZERO SCANNED IS NOT A PASS WHEN SOMETHING RELIES ON THIS TO GATE. The count
# is printed unconditionally because it is what makes a green readable, and
# --require-commits (which the workflow passes) turns an empty range into a
# refusal. A 3 from CI means look at the push, not at this script.
if [ "${scanned}" -eq 0 ]; then
    if [ "${require_commits}" -eq 1 ]; then
        printf 'ERROR: range %s resolved but scanned 0 commits.\n' "${range}" >&2
        printf 'Refusing to report a pass over a range that gates nothing.\n' >&2
        exit 3
    fi
    printf 'No commits in %s to check (0 scanned).\n' "${range}"
    exit 0
fi

printf 'All %d commit(s) in %s authored by %s <%s>.\n' \
    "${scanned}" "${range}" "${expected_name}" "${expected_email}"
