# ADR-0011: Delivery overlay layer for tool-specific Argo CD concerns

- **Status**: Accepted
- **Date**: 2026-06-07

## Context

ADR-0001 establishes that `sources/<app>` is organized by application, not delivery
tool. Every source directory must be consumable by any delivery mechanism — Argo CD,
Ansible, RHACM PolicyGenerator — without encoding assumptions about which tool is
active.

A recurring operational problem breaks this constraint: OLM operator subscriptions
accumulate orphaned ClusterServiceVersions (CSVs) across reconcile cycles. When Argo
CD syncs a subscription that was already installed, OLM creates a new CSV without
deleting the previous one. Argo CD then detects drift (unknown resource) and either
marks the app OutOfSync indefinitely or, with `prune: true`, deletes the active CSV
and triggers an unintended operator restart.

The correct fix is a Kubernetes `Job` with an `argocd.argoproj.io/hook: PreSync`
annotation. Before Argo CD renders and applies the subscription manifest, the PreSync
Job deletes any orphaned CSV in the operator's namespace, leaving OLM with a clean
slate. The Job is idempotent: if no orphaned CSVs exist, it exits 0 with no changes.

However, a `Job` annotated with `argocd.argoproj.io/hook` is purely an Argo CD
construct. It has no meaning to Ansible, RHACM, or any other tool. Placing it inside
`sources/<app>` would violate ADR-0001's "organized by application, not delivery tool"
principle and contaminate a path that must remain delivery-agnostic.

The same problem class extends beyond CSV cleanup:
- **Sync waves** (`argocd.argoproj.io/sync-wave`): ordering manifests within a sync
  that makes no sense outside Argo CD.
- **Resource exclusions**: omitting resources from Argo CD management while still
  having them declared in sources for other tools.
- **PostSync verification Jobs**: health checks that only fire after an Argo CD sync.

These are all Argo CD-specific delivery concerns. They need a home that is:
1. Clearly scoped to Argo CD delivery (not polluting `sources/`)
2. Opt-in per cluster — not every cluster that runs an operator needs the same hooks
3. Composable — multiple Argo CD concerns can be layered on a single source
4. Consistent with the cascade model from ADR-0003 — overrides accumulate per-cluster

## Decision

Introduce a `delivery/argo-cd/` tree alongside `sources/`. It contains two subtrees:

```
delivery/
└── argo-cd/
    ├── components/          # reusable Kustomize Components (tool-specific manifests)
    │   └── <concern>/
    │       ├── kustomization.yaml  (apiVersion: kustomize.config.k8s.io/v1alpha1, kind: Component)
    │       └── *.yaml
    └── overlays/            # per-app Kustomize overlays that compose sources/ + components
        └── <app>/
            └── kustomization.yaml  (resources: sources/<app>, components: <concern>/...)
```

### Kustomize Components (`delivery/argo-cd/components/<concern>/`)

Each component is a self-contained Kustomize Component (the `Component` kind, not a
full `Kustomization`). Components cannot be applied standalone — they are designed to
be included via a `components:` stanza in a parent kustomization. This prevents them
from being accidentally referenced as a direct Argo CD Application source.

Components may contain:
- Hook Jobs (PreSync, PostSync, SyncFail)
- Argo CD-specific annotations and labels (sync-wave, hook-delete-policy)
- Resource exclusion patches
- Any manifest that is only meaningful in the context of Argo CD reconciliation

### Overlays (`delivery/argo-cd/overlays/<app>/`)

An overlay is a standard Kustomize `Kustomization` that:
- References `sources/<app>` as a resource (relative path from repo root)
- Includes one or more components from `delivery/argo-cd/components/`
- May add patches specific to this app × concern combination

The overlay produces a complete, valid Argo CD Application source. It is the path
that Argo CD actually syncs from when Argo CD-specific concerns are needed.

### Gate file opt-in

A gate file that needs delivery overlays uses `templatePatch` to redirect
`spec.source.path` from `sources/<app>` to `delivery/argo-cd/overlays/<app>`:

```yaml
# clusters/<cluster>/lvm-storage.yaml
templatePatch: |
  spec:
    source:
      path: delivery/argo-cd/overlays/lvm-storage
```

Gate files that do not need delivery concerns continue to reference `sources/<app>`
with no change. The overlay path is intentionally per-app — the ApplicationSet default
(`sources/<app>`) remains clean.

### Naming and scope

- `delivery/argo-cd/` is the authoritative home for Argo CD delivery concerns. No
  Argo CD hooks, sync-wave annotations, or similar constructs belong in `sources/`.
- `delivery/` is the root for all future tool-specific delivery overlays. If an
  Ansible-specific pre-task manifest becomes necessary, it lives under
  `delivery/ansible/`, not in `sources/`.
- `sources/<app>` remains the single source of truth for *what* an application is.
  `delivery/` expresses *how* a specific tool delivers it.

## Consequences

**Positive:**

- `sources/<app>` stays delivery-agnostic. An Ansible playbook or RHACM
  PolicyGenerator consuming `sources/lvm-storage` never encounters an Argo CD hook
  Job.
- Argo CD delivery concerns are findable: all hooks, sync waves, and resource patches
  live in one predictable tree.
- Opt-in per cluster: a production cluster can include the CSV cleanup hook while a
  development cluster uses the plain source.
- Components are composable: a future overlay for `openshift-virtualization` can
  combine `olm-csv-cleanup` with a `sync-wave-operator-first` component without
  forking either.
- The cascade model from ADR-0003 is preserved: the default (no hook) lives at the
  org level; the override (with hook) lives in the per-cluster gate file.

**Negative / constraints:**

- An overlay duplicates the `spec.source.path` reference to `sources/<app>`. If the
  source directory is renamed, the overlay must be updated. This is an acceptable
  cost: directory renames are rare and the link is explicit.
- Argo CD Application resources now come from two distinct paths (sources and overlay).
  Tooling that assumes all manifests live under `sources/` must be updated to
  understand `delivery/argo-cd/overlays/` as a valid Application source root.
- A cluster that opts into an overlay gets the full overlay content. There is no
  mechanism to include part of a component. Components must be designed for complete
  inclusion or split into finer-grained units.
- Kustomize `components:` requires Kustomize v4.1+. Argo CD 2.x ships with Kustomize
  v4+, so this is not a constraint in practice.

## Alternatives considered

### Embed hooks in `sources/<app>` behind a Kustomize overlay

A `sources/lvm-storage/overlays/argo-cd/` subdirectory inside sources could include
the hook. This keeps everything under one application path but violates ADR-0001's
"not by delivery tool" constraint and conflates application content with delivery
mechanism.

### Separate Argo CD Application per hook

Deploy the PreSync Job as its own Argo CD Application with a `sync-wave: "-1"` on the
parent Application. This avoids touching sources/ but requires two ApplicationSet
entries per operator and makes the "hook fires before sync" ordering implicit and
fragile.

### Annotations on the Subscription manifest itself

Annotating `sources/lvm-storage/subscription.yaml` with `argocd.argoproj.io/sync-wave`
puts Argo CD semantics directly in sources. While less disruptive than a full hook
Job, it still violates ADR-0001 and creates noise for non-Argo CD tools.

## Related

- ADR-0001: Organize sources by application, not delivery tool
- ADR-0003: Organizational defaults over boilerplate
- `delivery/argo-cd/components/olm-csv-cleanup/` — reference implementation
- `delivery/argo-cd/overlays/lvm-storage/` — example overlay for lvm-storage
