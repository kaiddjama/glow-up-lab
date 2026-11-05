#!/usr/bin/env bash
# Alerte inventaire: opens (or comments on) one GitHub issue, which notifies the repository owner by e-mail and in
# the GitHub app. At most one comment every 3 hours on an open alert, so a recurring failure does not flood her.
# Usage: alert.sh "title" "body"   (needs GH_TOKEN with issues: write, GH_REPO)
set -euo pipefail
title="$1"; body="$2"
gh label create alerte-inventaire --color B60205 --description "Problème d'inventaire non résolu automatiquement" --force >/dev/null 2>&1 || true
num=$(gh issue list --label alerte-inventaire --state open --json number -q '.[0].number' || true)
if [ -z "$num" ]; then
  gh issue create --label alerte-inventaire --title "$title" --body "$body"
  exit 0
fi
last=$(gh issue view "$num" --json updatedAt -q .updatedAt)
age=$(( $(date +%s) - $(date -d "$last" +%s) ))
if [ "$age" -gt 10800 ]; then
  gh issue comment "$num" --body "$title"$'\n\n'"$body"
else
  echo "Alert already raised less than 3 h ago (issue #$num): not repeated."
fi
