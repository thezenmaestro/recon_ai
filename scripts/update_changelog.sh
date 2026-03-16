#!/usr/bin/env bash
# scripts/update_changelog.sh
# Regenerates the "Recent Commits" section of CHANGELOG.md (last 10 commits).
# Everything below the <!-- HISTORICAL --> marker is preserved unchanged.
# Run manually or called automatically by the post-commit hook.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
CHANGELOG="$REPO_ROOT/CHANGELOG.md"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
GENERATED_AT="$(date -u '+%Y-%m-%d %H:%M UTC')"
MARKER="<!-- HISTORICAL -->"

# Build the auto-generated header + recent commits section
{
  echo "# Changelog"
  echo ""
  echo "> Auto-generated recent commits — branch \`${BRANCH}\`. Updated: ${GENERATED_AT}"
  echo "> Full narrative history below the divider."
  echo ""
  echo "---"
  echo ""
  echo "## Recent Commits (last 10)"
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
} > "${CHANGELOG}.tmp"

# Append the historical section if it exists in the current file
if [ -f "$CHANGELOG" ] && grep -q "$MARKER" "$CHANGELOG"; then
  echo "$MARKER" >> "${CHANGELOG}.tmp"
  echo "" >> "${CHANGELOG}.tmp"
  # Extract everything after the marker
  awk "/$MARKER/{found=1; next} found{print}" "$CHANGELOG" >> "${CHANGELOG}.tmp"
fi

mv "${CHANGELOG}.tmp" "$CHANGELOG"
echo "CHANGELOG.md updated (last 10 commits, historical section preserved)."
