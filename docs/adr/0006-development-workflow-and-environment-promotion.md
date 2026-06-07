# ADR-0006: Development workflow and environment promotion

- **Status**: Accepted
- **Date**: 2026-06-03

## Context

GitOps repos are often treated as write-first: define the desired state in git,
then observe the effect on the cluster. This works well for steady-state operations
but creates friction during development, where the feedback loop is:
write → commit → push → wait for sync → observe → repeat.

For platform and application development, a tighter inner loop is needed. The
desired state is not known in advance; it is discovered by experimenting on a live
cluster. Forcing git commits as the entry point to that loop is toil that slows
exploration and adds noise to git history.

Additionally, this repo serves multiple environments (dev, test, prod). Each
environment has different stability requirements and a different relationship to
git history. Treating all environments the same conflates "works on my cluster"
with "ready for production."

## Decision

### Development inner loop

Development follows a **cluster-first, git-second** flow:

1. **Experiment on a dev cluster** — use the Argo CD UI, `oc`/`kubectl`, or `helm`
   directly on the cluster. No git commits, no pushes. The cluster is the
   scratchpad.

2. **Capture what works** — once a configuration is proven on the cluster, commit
   it to a `sources/<app>/` directory on a feature branch. The git history should
   reflect decisions, not experiments.

3. **Wire it to Argo CD when ready** — add a gate file to
   `clusters/<cluster>/<app>.yaml` when the app is stable enough to be
   continuously reconciled. Premature Argo CD adoption generates noise and sync
   failures during active development.

4. **The loop stays tight** — avoid any step that requires pushing to a remote,
   waiting for CI, or obtaining a review before seeing the effect on the cluster.
   Those gates belong at promotion time, not in the inner loop.

This approach treats the dev cluster as a REPL: fast, ephemeral, low-ceremony.
Git is where durable decisions land.

### Environment definitions and git promotion

Each environment has a defined relationship between clusters and git:

| Environment | `targetRevision` | When to promote |
|---|---|---|
| `dev` | Feature branch or `HEAD` | After the inner loop produces a working configuration |
| `test` | `HEAD` (main branch) | After feature branch is reviewed and merged |
| `prod` | Semver tag (e.g., `v1.2.0`) | After test validation passes; explicit tag cut |

**Dev** clusters track a feature branch or HEAD. Multiple feature branches may be
active on different dev clusters simultaneously. Dev clusters are allowed to drift
and be broken; they are development tooling, not production infrastructure.

**Test** clusters track HEAD of the main branch. Merging a feature branch
automatically promotes it to test. Test clusters should be stable; broken merges
to main are treated as incidents.

**Prod** clusters track explicit semver tags. Promotion to prod is a deliberate
act: cut a tag, update the prod cluster's `targetRevision`. No automatic promotion.
This gives production a stable, auditable config reference that does not change
until explicitly promoted.

### ApplicationSet targetRevision override

The default `targetRevision: HEAD` from the ApplicationSet template applies to all
clusters. A cluster can override this in its gate file:

```yaml
# clusters/rdu-sno-prd-1/my-app.yaml
spec:
  source:
    targetRevision: v1.2.0
```

Or for all apps on a cluster at once, the cluster's `app-of-apps.yaml` can patch
the ApplicationSet's default `targetRevision` via the Kustomize overlay.

Since `spec.source.targetRevision` is in `ignoreApplicationDifferences`, operators
can also change the revision in the Argo CD UI without triggering a git revert —
useful for emergency rollbacks and feature-branch testing on a shared cluster.

### Team-controlled git repos

Teams that need full control of their source revision can maintain their own git
repo. They add a gate file that overrides `spec.source.repoURL` and
`spec.source.targetRevision` to point at their repo, while inheriting all org
defaults for destination, project, and sync policy:

```yaml
# clusters/rdu-sno-dev-1/my-team-apps.yaml
spec:
  source:
    repoURL: https://github.com/my-team/my-team-apps.git
    targetRevision: HEAD
    path: sources/my-team-apps
```

## Consequences

**Positive:**

- The inner development loop requires no git operations — it is as fast as applying
  YAML directly to a cluster.
- Git history is intentional: it captures proven configurations, not experiments.
- Environment promotion is explicit and auditable. Prod never moves without a
  deliberate tag cut.
- Emergency overrides (revision pinning in the UI) are preserved across syncs via
  `ignoreApplicationDifferences`.

**Negative / constraints:**

- Dev clusters may be significantly ahead of or behind the main branch. They are
  not a reliable reflection of what is in git; that is intentional and expected.
- The discipline of "capture what works" (step 2) relies on operators. Configs
  proven on a cluster but never committed to git are lost when the cluster is
  rebuilt. This is a process constraint, not a technical one.
- Prod cluster configs (semver tags) require a manual tag-cut step as part of
  the release process. This must be documented in team runbooks.

## Related

- ADR-0002: Application naming convention
- ADR-0003: Organizational defaults over boilerplate
- ADR-0005: Flywheel self-reference and bootstrapping seams
- `ignoreApplicationDifferences` in `sources/app-of-apps/applicationset.yaml`
