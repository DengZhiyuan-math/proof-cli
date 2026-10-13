#!/bin/bash
# Point every PR in the ADR-0021 batch at its repository's integration branch, then print each PR's base.
# Run before the integration merges are pushed, so GitHub marks each PR merged when its head lands.
set -u

retarget() {  # repo base pr...
  repo=$1; base=$2; shift 2
  for pr in "$@"; do
    current=$(gh pr view "$pr" --repo "$repo" --json baseRefName -q .baseRefName) || { echo "!! $repo#$pr: cannot read"; continue; }
    if [ "$current" != "$base" ]; then
      gh pr edit "$pr" --repo "$repo" --base "$base" >/dev/null && echo "$repo#$pr: $current -> $base"
    fi
  done
  for pr in "$@"; do
    gh pr view "$pr" --repo "$repo" --json number,state,baseRefName,headRefName,headRefOid \
      -q '"  #\(.number) \(.state) \(.headRefName)@\(.headRefOid[0:7]) -> \(.baseRefName)"'
  done
}

retarget DengZhiyuan-math/proof-cli integ/0021 204 205 206 207 208 209
retarget zeqome/proof-agents integ/0021 21 22 23 24 25 26
retarget zeqome/proof-web feat/0021-pursue-review-queue 13 14 15 16 19 21
