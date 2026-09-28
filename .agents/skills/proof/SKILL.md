---
name: "proof-repo-dev"
description: "Repository-local debug helper for Proof CLI command routing"
metadata:
  short-description: "Proof repo debug helper"
---

# Proof CLI Repository Debug Helper

This project-local skill is for repository debugging only.

Canonical everyday entry paths are:

- the global exact `$proof-*` skills
- the `proof` CLI, rooted by `--root` or `$PROOF_ROOT` (see the `proof-cli` skill)

Do not rely on this local helper as the main user-facing trigger surface.
