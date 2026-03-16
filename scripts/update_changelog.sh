#!/usr/bin/env bash
# scripts/update_changelog.sh
# Regenerates CHANGELOG.md at the repo root with the last 10 commits.
# Run manually or called automatically by the post-commit hook.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
CHANGELOG="$REPO_ROOT/CHANGELOG.md"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
GENERATED_AT="$(date -u '+%Y-%m-%d %H:%M UTC')"

{
  echo "# Changelog"
  echo ""
  echo "> Auto-generated — last 10 commits on branch \`${BRANCH}\`. Updated: ${GENERATED_AT}"
  echo ""
  echo "---"
  echo ""

  git log --pretty=format:"%H|%h|%ad|%an|%s" --date=short -10 | \
  while IFS='|' read -r full_hash short_hash date author subject; do
    echo "### \`${short_hash}\` — ${subject}"
    echo ""
    echo "| Field  | Value |"
    echo "|--------|-------|"
    echo "| Date   | ${date} |"
    echo "| Author | ${author} |"
    echo "| Commit | \`${full_hash}\` |"
    echo ""

    body="$(git log -1 --pretty=format:"%b" "$full_hash" | sed '/^$/d')"
    if [ -n "$body" ]; then
      echo "$body"
      echo ""
    fi

    echo "---"
    echo ""
  done
} > "$CHANGELOG"

echo "CHANGELOG.md updated (last 10 commits)."
