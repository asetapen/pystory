#!/usr/bin/env bash
# Fail if any commit in a range was authored by something other than Adam.
#
# Agents commit to this repo on his behalf, and a misconfigured agent shell
# silently stamps its own identity instead (GIT_AUTHOR_NAME in the environment
# overrides git config, so nothing errors and the push succeeds). That is how
# c85097c reached feature/desklock-obsbot-s3-recognition authored
# "crew/st/sauron <crew.st.sauron@vapor.city>": ten handoffs cited that SHA and
# none of them read its author. Once such a commit merges, the authorship is
# permanent.
#
# Scans a RANGE, not all of history, because the two
# adam.setapen@remedyrobotics.com commits predate this repo's conventions and
# are already ancestors of main. Only new work is held to the rule.
#
# Usage: check-commit-authors.sh [<range>]     (default: origin/main..HEAD)
set -euo pipefail

range="${1:-origin/main..HEAD}"

expected_name="Adam Setapen"
expected_email="asetapen@gmail.com"

# Resolve the range BEFORE scanning it. `git log` inside a process
# substitution cannot fail this script: the subshell's exit status is
# discarded, so `set -e` never sees it and an unresolvable range reads as
# "zero commits, all clean" and exits 0. That is the exact false green this
# check exists to prevent -- CI runs behind actions/checkout, which clones
# shallow and need not have origin/main at all, so the failure mode is
# reachable rather than theoretical.
if ! git rev-list "$range" >/dev/null 2>&1; then
    printf 'ERROR: cannot resolve range %s (shallow clone, or missing ref?).\n' "$range" >&2
    printf 'Refusing to report a pass over a range this script cannot read.\n' >&2
    exit 2
fi

# %an/%ae are the AUTHOR, not the committer: the committer is legitimately
# vapor-city on agent-made commits, and rewriting that is not the goal.
bad=0
while IFS=$'\t' read -r sha name email; do
    [ -n "$sha" ] || continue
    if [ "$name" != "$expected_name" ] || [ "$email" != "$expected_email" ]; then
        printf 'BAD AUTHOR %s: %s <%s>\n' "$sha" "$name" "$email" >&2
        bad=$((bad + 1))
    fi
done < <(git log --no-merges --format='%H%x09%an%x09%ae' "$range")

if [ "$bad" -gt 0 ]; then
    printf '\n%d commit(s) in %s are not authored by %s <%s>.\n' \
        "$bad" "$range" "$expected_name" "$expected_email" >&2
    printf 'Rebase amending the author, or squash-merge so the merge commit carries it.\n' >&2
    exit 1
fi

printf 'All commits in %s authored by %s <%s>.\n' "$range" "$expected_name" "$expected_email"
