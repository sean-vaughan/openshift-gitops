# ADR-0008 — Branch Protection and Repository Governance

**Status:** Accepted  
**Date:** 2026-06-07  
**Deciders:** Platform Architecture

---

## Context

`openshift-gitops` is the source of truth for all cluster configurations. A direct
push to `main` immediately affects every cluster that tracks `HEAD`. Early in the
repo's life, direct pushes to `main` occurred under operational pressure (live
cluster recovery, hotfixes during re-bootstrap). Each incident resulted in changes
that bypassed review and violated ADR-0006 (development workflow).

Two failure modes are eliminated by mechanical enforcement rather than discipline:

1. **Accidental direct push** — a distracted or pressured engineer pushes directly
   to `main`, skipping PR review and CI validation.
2. **Force push** — history rewrite on `main` breaks any branch whose history
   depends on the rewritten commits, and destroys the audit trail.

A third failure mode is addressed by policy rather than mechanics:

1. **Emergency bypass** — a genuine break-glass situation requires a fast path.
   The rule must accommodate this without undermining normal governance.

---

## Decision

### GitHub branch protection on `main`

The following rules are enforced via GitHub branch protection:

| Rule | Setting | Rationale |
|------|---------|-----------|
| Require pull request | Enabled (0 approvers) | Forces PR flow; enables CI hooks |
| Dismiss stale reviews | Disabled | Solo/small-team repo; not needed |
| Require status checks | None configured initially | Add when CI pipeline exists |
| Require linear history | Disabled | Merge commits are acceptable |
| Allow force pushes | **Disabled** | Protects audit trail unconditionally |
| Allow branch deletion | **Disabled** | Prevents accidental `main` deletion |
| Restrict pushes to admins | **Disabled** | Allows admin emergency access |

**Why 0 required approvers?** This is a solo/small-team repo. The value of the
PR flow is the audit trail, CI gate, and the deliberate context-switch — not
peer review of every line. Add required reviewers when the team size warrants it.

**Why not enforce admins?** Admins retain the ability to merge without a PR in a
genuine break-glass situation. This is intentional — see the emergency procedure
below. The risk of abuse is accepted in exchange for operational flexibility.

### Branch naming convention

| Branch type | Pattern | Purpose |
|------------|---------|---------|
| Feature / change | `feature/<short-description>` | Normal development |
| Hotfix | `hotfix/<short-description>` | Break-glass: expedited PR |
| Release | `release/<version>` | Reserved for future use |

### Commit message convention

No enforced format (no commit-msg hook). By convention:

```
<type>: <short description>

<body — what and why, not how>

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

Types: `feat`, `fix`, `docs`, `chore`, `refactor`. The `Co-Authored-By` trailer
is included when AI assistance materially contributed to the change.

### Emergency procedure (break-glass)

When a cluster is actively broken and a direct fix is needed faster than a PR
review cycle:

1. Create a `hotfix/<description>` branch — takes 10 seconds.
2. Commit the fix to the branch.
3. Open a PR with `[BREAK-GLASS]` in the title and merge immediately.
4. The PR provides the audit trail; the branch protection ensures the push
   is recorded even when expedited.

A direct push to `main` (bypassing this) requires an admin override of branch
protection, which GitHub logs. This should be treated as an exceptional event
and documented in a follow-up commit to `docs/adr/` or a GitHub issue.

---

## Consequences

### Positive

- Every change to `main` has a PR in the audit trail, regardless of size.
- Force pushes are mechanically impossible, protecting cluster history.
- The PR flow creates a natural point for future CI hooks (linting, schema
  validation, kustomize build checks).
- AI-assisted changes are attributed via `Co-Authored-By` trailer.

### Negative

- A small overhead for trivial changes (typo fixes, comment updates).
  Mitigation: PRs can be opened and merged immediately for solo work.
- The 0-approver setting means the protection is primarily mechanical
  (audit trail) rather than social (peer review). Accepted for current team size.

### Neutral

- Existing `feature/gitops-flywheel` branch is unaffected; only `main` is
  protected.
- CI status checks are not required initially. Add via a separate ADR when a
  CI pipeline is implemented.

---

## Implementation

Branch protection was applied via `gh api`:

```bash
gh api repos/sean-vaughan/openshift-gitops/branches/main/protection \
  --method PUT --input - <<'EOF'
{
  "required_status_checks": null,
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "required_approving_review_count": 0,
    "dismiss_stale_reviews": false
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
EOF
```

---

## Related

- [ADR-0006 — Development workflow and environment promotion](0006-development-workflow-and-environment-promotion.md)
