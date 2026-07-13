---
name: sync-docs
description: >-
  Check whether README.md and the header comment/docstring of each
  changed script (ci/*.sh, ci/*.py, .github/workflows/*.yml) still
  accurately describe current behavior after a code change, and fix
  any drift found. Invoke proactively before committing a change that
  touches the build/CI pipeline (ci/, .github/workflows/, images.yaml),
  or whenever explicitly asked to update docs/README/comments for a
  recent change. Do not invoke for changes with no doc surface (pure
  test files, unrelated app code under base/desktop/apps).
---

# sync-docs

This repo has a strong, established convention: every `ci/*.sh`,
`ci/*.py` and `.github/workflows/*.yml` file opens with a header
comment/docstring that explains its flow, the env vars it consumes,
and the non-obvious "why" behind its design choices. README.md mirrors
some of that (Build matrix & tagging, the GitHub table, Image
catalogs). Both drift from the code easily — this skill is the review
pass that catches it, modeled on the doc updates already made
throughout this project's CI work (see git log for `ci:`/`fix(ci):`
commits — each one updated the relevant header comment and, where
applicable, README.md in the same commit).

## Procedure

1. **Scope the diff.** Use `git diff` (uncommitted) or `git diff
   HEAD~1` / `git show` (already committed, if asked about a past
   change) to see exactly what changed. Only look at files under
   `ci/`, `.github/workflows/`, `images.yaml`, and any `manifest.yaml`
   whose schema-relevant fields changed.

2. **For each changed script**, re-read its own header comment/docstring
   top-to-bottom and check it against the NEW code for concrete drift:
   - Flow description (e.g. "build → smoke → push") — does the step
     order/count still match?
   - Env var names it claims to read/require — still accurate?
   - Named tools/images/registries it references (versions, hosts) —
     still correct?
   - Stated rationale ("why X instead of Y") — is the constraint that
     justified it still true, or did the code just move past it?
   - Cross-references to other files/jobs by name — still exist under
     that name?

3. **For each changed subsystem**, grep README.md for related keywords
   (job names, env var names, tool names, registry hosts, file paths)
   to find sections describing the same thing, and check those the
   same way. Relevant sections today: "Build matrix & tagging", the
   GitHub table (Workflow/Runners/Registry/Signing), "Image catalogs",
   "Image metadata". Don't assume this list is exhaustive — grep first.

4. **Fix only the drift you found.** Match this repo's existing
   comment style exactly:
   - Terse, explains the WHY (a hidden constraint, a workaround, a
     past incident), never the WHAT (identifiers already say that).
   - No comment at all if nothing non-obvious would be lost by
     removing it.
   - No multi-paragraph docstrings, no restating obvious code.
   - Do not add new documentation sections or expand scope beyond what
     the diff actually changed — this is a correction pass, not a
     rewrite or an invitation to document previously-undocumented
     behavior unrelated to the change.

5. **Report back concisely**: which files got a doc fix and one line
   on why, and which changed files were checked and found already
   accurate (so nothing was silently skipped). Do not create a
   separate summary document — this goes in the chat response.

## When NOT to touch something

- A change that's purely internal to a function body, with no effect
  on the behavior the header/README actually describes (e.g. a
  variable rename that doesn't change semantics).
- Generated/vendored files (`catalog-*.yaml`, `github-matrices.json`,
  `Dockerfile.generated`, `ci/schema/`).
- Anything in `base/`, `desktop/`, `apps/` unless the change is to
  `manifest.yaml` fields that README's Build matrix section documents
  (`from`, `archs`, `version` semantics) — per-image Dockerfiles are
  not part of this skill's scope.
