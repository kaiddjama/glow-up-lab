#!/usr/bin/env bash
# Alerte inventaire: opens (or comments on) a GitHub issue, which notifies the repository owner by e-mail and in the GitHub
# app. One open issue per alert title: a new kind of problem is never swallowed by an older open alert. The same alert is
# repeated at most every 3 hours, so a recurring failure does not flood her.
# Usage: alert.sh "title" "body"   (needs GH_TOKEN with issues: write, GH_REPO)
set -euo pipefail
title="$1"; body="$2"
gh label create alerte-inventaire --color B60205 --description "Problème d'inventaire non résolu automatiquement" --force >/dev/null 2>&1 || true
num=$(gh issue list --label alerte-inventaire --state open --limit 100 --json number,title \
      | jq -r --arg t "$title" '[.[] | select(.title == $t)][0].number // empty' || true)
if [ -z "$num" ]; then
  gh issue create --label alerte-inventaire --title "$title" --body "$body"
  exit 0
fi
last=$(gh issue view "$num" --json updatedAt -q .updatedAt)
age=$(( $(date +%s) - $(date -d "$last" +%s) ))
if [ "$age" -gt 10800 ]; then
  gh issue comment "$num" --body "$body"
else
  echo "Alert already raised less than 3 h ago (issue #$num): not repeated."
fi
