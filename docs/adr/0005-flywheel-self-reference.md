# ADR-0005: Flywheel self-reference and bootstrapping seams

- **Status**: Accepted
- **Date**: 2026-06-03

## Context

This repo uses a "flywheel" pattern: a small set of platform components, once
running, continuously reconcile the full desired state of every cluster. The
ApplicationSet generates Applications; those Applications deploy sources; some of
those sources include the ApplicationSet itself and the cluster secrets that make
the ApplicationSet work.

This creates intentional self-references:

- The `app-of-apps` ApplicationSet is itself deployed as an Argo CD Application
  managed by the same ApplicationSet.
- The cluster secret that Argo CD needs to generate Applications is deployed by one
  of those Applications.
- AppProjects that Applications belong to are deployed by Applications.

These look like circular dependencies — A needs B which needs A — and circular
dependencies are rightly treated as a design smell. However, these are not circular
dependencies in the traditional sense. Each self-reference has a defined
**bootstrapping seam**: a one-time manual step that breaks the cycle for the first
deployment. After that step, the flywheel is self-sustaining.

Failing to acknowledge these seams leads to broken bootstraps and confusing errors.
Failing to document which seams are acceptable vs. which indicate a design problem
leads to accumulating accidental complexity.

## Decision

Self-referencing, self-managing components are explicitly preferred over external
management in this repo. The flywheel property — the repo reconciling itself — is
a feature, not a bug.

Every self-reference must be documented with:

1. **What it is**: which component references which other component.
2. **Why it is intentional**: what property it provides.
3. **The bootstrapping seam**: the exact manual step required on first deployment.

### Documented self-references

#### 1. `app-of-apps` manages itself

The `clusters/<cluster>/app-of-apps.yaml` gate file causes the ApplicationSet to
generate an Application for `sources/app-of-apps`. That Application's source is
`clusters/<cluster>/app-of-apps/`, a Kustomize overlay that renders the
ApplicationSet manifest itself.

- **Why**: The ApplicationSet stays in sync with git. Changes to generator config,
  `ignoreApplicationDifferences`, or template defaults are applied automatically.
- **Bootstrapping seam**: The ApplicationSet must be applied manually once
  (via `kubectl apply` or Ansible) before it can manage itself.

  ```
  kubectl apply -k clusters/<clusterName>/app-of-apps/
  ```

  After this, Argo CD takes over and the ApplicationSet manages itself.

#### 2. Cluster secret deployed by the app it enables

The cluster secret (`clusters/<cluster>/app-of-apps/cluster-secret.yaml`) is part
of the `app-of-apps` Application source. Argo CD needs the cluster secret to
generate Applications — but the cluster secret is deployed by an Application.

- **Why**: The cluster secret stays in git. Cluster identity is version-controlled,
  audited, and not a manual artifact. Per ADR-0004, the secret uses the real cluster
  name, which matches every Application name and gate file.
- **Bootstrapping seam**: Resolved by the same `kubectl apply -k` in seam #1 above.
  The cluster secret and ApplicationSet are in the same Kustomize overlay, so a
  single apply delivers both.

#### 3. AppProjects deployed by Applications that belong to them

Applications belong to AppProjects. AppProjects are deployed by Applications
(the `app-projects` Application). Before the `app-projects` Application syncs,
the AppProjects it manages do not exist, and any Application assigned to those
projects will fail validation.

- **Why**: AppProjects stay in git and are version-controlled. Adding or modifying
  a project is a pull request, not a manual operation.
- **Bootstrapping seam**: Apply the `app-projects` source out-of-band before or
  immediately after bootstrapping the ApplicationSet.

  ```
  helm template sources/app-projects/chart \
    -f sources/app-projects/platform.yaml \
    | kubectl apply -f -
  ```

  Alternatively, temporarily assign new Applications to the `default` AppProject
  until `app-projects` has synced, then update. The `default` project exists in
  every Argo CD installation.

### Design rules

1. Every new self-reference introduced to this repo must be documented in this ADR
   or in a successor ADR that references this one.

2. Self-references that cannot be resolved by a one-time manual bootstrap step are
   not acceptable. If component A can never exist without component B, and B can
   never exist without A, the design must change.

3. The self-managed `app-of-apps` Application is configured with
   `syncPolicy.automated.prune: false` and `selfHeal: false`. This is intentional:
   Argo CD must not automatically delete or revert the ApplicationSet that manages
   it. Changes to the ApplicationSet are reconciled on the next sync, but only after
   they have been committed to git and reviewed.

## Consequences

**Positive:**

- The entire cluster configuration — including the GitOps tooling itself — is
  version-controlled and drift-free after bootstrapping.
- Adding a cluster is a git commit (new gate files and cluster secret) plus a single
  `kubectl apply`. All subsequent state is managed by the flywheel.
- The bootstrapping seams are explicit and documented. Operators know exactly what
  must be done manually vs. what is automated.

**Negative / constraints:**

- The bootstrapping sequence matters. Applying resources in the wrong order produces
  transient errors. The documented bootstrap order is:
  1. `kubectl apply -k clusters/<clusterName>/app-of-apps/` (delivers ApplicationSet
     and cluster secret in one step).
  2. Wait for `app-of-apps` Application to sync and reach Healthy state.
  3. `app-projects` Application syncs automatically; AppProjects are created.
  4. All other Applications sync in dependency order (Argo CD sync waves if needed).
- Self-managing components require careful review: a bad commit to
  `sources/app-of-apps/` can break the ApplicationSet and prevent all subsequent
  syncs. Changes to that source should be tested on a non-production cluster first.

## Related

- ADR-0003: Organizational defaults over boilerplate
- ADR-0004: Named cluster secrets
- `clusters/<clusterName>/app-of-apps/kustomization.yaml`
- `clusters/<clusterName>/app-of-apps/cluster-secret.yaml`
