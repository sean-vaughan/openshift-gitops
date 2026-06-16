# ADR-0010: Cluster upgrade strategy

- **Status**: Accepted
- **Date**: 2026-06-07

## Context

OpenShift clusters upgrade via the Cluster Version Operator (CVO), which watches
the `ClusterVersion` singleton CR (`version`). Two fields drive upgrade behavior:

- **`spec.channel`** — which update graph the CVO consults. The CVO will apply
  available updates automatically if `spec.desiredUpdate` is absent.
- **`spec.desiredUpdate`** — an explicit target version (and optionally a sha256
  image pin). When present, the CVO upgrades to exactly that version and stops.

Without GitOps management, `ClusterVersion` is edited ad-hoc and its state is
not captured in the repo. This creates drift: the channel or version pin on a
production cluster may differ from what anyone expects, and there is no PR trail
for upgrade decisions.

This repo already manages all Argo CD Application configuration via the
app-of-apps pattern. Cluster upgrades should follow the same model: desired state
declared in git, applied by Argo CD, deviations visible as Argo CD sync drift.

### Constraints

1. `ClusterVersion` is a cluster-scoped singleton — there is exactly one per
   cluster, named `version`. It cannot be created by Argo CD; it must be patched.
2. Argo CD must be configured with `ignoreDifferences` for `status.*` and
   `spec.clusterID` (immutable, set at install time) to avoid perpetual drift.
3. Minor-version upgrades (e.g., 4.20 → 4.21) require an `AdminAcknowledgement`
   object in the `openshift-config` namespace before the CVO will proceed.
   This acknowledgement is itself a Kubernetes resource and belongs in
   `sources/cluster-version/`.
4. Some minor-version upgrades carry additional preconditions (e.g., 4.20 → 4.21
   requires Sigstore signature mirrors for any cluster with mirror registries
   configured). These are surfaced as `Upgradeable=False` conditions on the
   `ClusterVersion` status. The PR that bumps the channel should document that
   the precondition has been satisfied.

## Decision

### Source structure

`sources/cluster-version/` is a Kustomize source that manages the `ClusterVersion`
CR. The base manifest sets only `spec.channel` — no `spec.desiredUpdate`. This
is the org default: channel-tracking with automatic patch upgrades.

```
sources/cluster-version/
  kustomization.yaml
  cluster-version.yaml        # spec.channel only; no desiredUpdate
```

### Channel tracking (dev clusters)

Dev and lab clusters use the base with no gate-file overrides. The CVO tracks
the declared channel and applies available updates automatically. No PR is
required for patch-level upgrades within the channel.

The base channel (`stable-4.20` as of this ADR) is updated by a PR to
`sources/cluster-version/cluster-version.yaml` when the org is ready to allow
all channel-tracking clusters to begin receiving that channel's updates.

### Version pinning (prod clusters)

Production clusters use a `templatePatch` in their gate file to add
`spec.desiredUpdate`:

```yaml
# clusters/<prod-cluster>/cluster-version.yaml
spec:
  source:
    path: sources/cluster-version
  ignoreDifferences:
    - group: config.openshift.io
      kind: ClusterVersion
      jsonPointers:
        - /spec/clusterID
        - /status
  templatePatch: |
    spec:
      spec:
        desiredUpdate:
          version: "4.20.19"
          image: "quay.io/openshift-release-dev/ocp-release@sha256:e37bcdba07c7312607363ddf5a8e317e4b6952b1465704b38c9a081d095697be"
```

The PR to update `desiredUpdate` in a prod gate file is the upgrade approval
gate. The sha256 image pin ensures the cluster upgrades to exactly the tested
release, not whatever the channel resolves to at sync time.

### Minor-version upgrade sequence

Bumping from one minor version to the next (e.g., 4.20 → 4.21) requires:

1. **Satisfy preconditions** — resolve any `Upgradeable=False` conditions. For
   4.20 → 4.21 this includes configuring Sigstore signature mirrors on any
   cluster with mirror registries.
2. **Admin acknowledgement** — add an `AdminAcknowledgement` manifest to
   `sources/cluster-version/`. This is a one-time object per minor-version
   boundary:

   ```yaml
   apiVersion: operator.openshift.io/v1
   kind: AdminAcknowledgement
   metadata:
     name: ack-4.20-kube-1.33-api-removals-in-4.21
     namespace: openshift-config
   spec:
     acknowledgedConditions:
       - type: "AdminAckRequired"
         version: "4.20"
   ```

3. **Update `spec.channel`** in the base (for dev) or gate file (for prod) in
   the same PR or a follow-on PR.

The PR that introduces the `AdminAcknowledgement` is the organizational sign-off
that the minor-version upgrade is approved. It must not be merged until all
preconditions documented in the `Upgradeable` condition message are satisfied.

### Argo CD Application configuration

The Argo CD Application for `cluster-version` must be configured with
`ignoreDifferences` to avoid perpetual drift from fields Argo CD cannot own:

```yaml
ignoreDifferences:
  - group: config.openshift.io
    kind: ClusterVersion
    jsonPointers:
      - /spec/clusterID
      - /status
```

This is declared as an org default in the ApplicationSet template, not repeated
in each gate file (per ADR-0003).

### Argo CD sync policy

`cluster-version` Applications use `syncPolicy.automated` with
`prune: false` — automated sync keeps the channel current but never deletes
the `ClusterVersion` CR (which would be rejected by the API server anyway).
`selfHeal: true` is appropriate for dev clusters; prod clusters may set
`selfHeal: false` to prevent unattended re-application of a version pin.

## Consequences

**Positive:**

- Every channel change and version pin is a PR: fully auditable, reviewable, and
  reversible by reverting the commit.
- Dev clusters upgrade automatically within their channel; no manual intervention
  for patch releases.
- Prod upgrades require an explicit PR with a sha-pinned version — the same
  workflow as any other config change, requiring the same review and CI gates.
- Minor-version upgrade approvals are captured as `AdminAcknowledgement` manifests
  in git, providing a durable record that preconditions were checked.

**Negative / constraints:**

- Argo CD cannot fully reconcile `ClusterVersion` — `spec.clusterID` and `status`
  must be ignored. Any drift in those fields will never be flagged.
- If `selfHeal: true` is set on a prod cluster and a version pin is in the gate
  file, Argo CD will re-apply the pin after any manual `oc edit clusterversion`.
  This is intentional (git is the source of truth) but operators must know not
  to expect ad-hoc edits to persist.
- The sha256 image pin in prod gate files must be updated for every upgrade.
  There is no automation to propose these PRs; a human or agent must look up the
  correct sha for the target release from the Cincinnati graph or release notes.
- `AdminAcknowledgement` objects accumulate in `sources/cluster-version/` over
  time as minor-version boundaries are crossed. They are harmless once applied
  but should be pruned periodically to keep the directory readable.

## Related

- ADR-0003: Organizational defaults over boilerplate
- ADR-0006: Development workflow and environment promotion
- `sources/cluster-version/`
- `clusters/k8s-sno/cluster-version.yaml`
- [OpenShift update documentation](https://docs.redhat.com/en/documentation/openshift_container_platform/4.20/html/updating_clusters/)
