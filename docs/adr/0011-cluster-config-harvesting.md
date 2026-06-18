# ADR-0011: Cluster config harvesting

- **Status**: Proposed
- **Date**: 2026-06-16

## Context

This repo is the source of truth for cluster configuration, but it was not
born that way. Existing clusters — `k8s-sno` foremost among them — already carry
custom configuration that was applied by hand, by the web console, or by earlier
tooling, and was never captured in git. The project roadmap calls this out
explicitly: an early phase is to **import existing k8s-sno configuration into the
flywheel**. New clusters will accumulate the same drift over time as operators
make "temporary" console edits that outlive their intent.

Argo CD does not help here. GitOps reconciliation is one-directional: git is the
desired state, the cluster is the live state, and Argo CD drives live toward
desired. It can report drift for resources it *already manages*, but it has no
facility to **discover** unmanaged config or **export** live resources back into
git. The reverse direction — cluster → git — is deliberately outside Argo CD's
scope, because the entire point of GitOps is to make that direction unnecessary
once the repo is authoritative. Getting *to* that authoritative state is a
one-time (per cluster, per resource) bootstrapping problem that Argo CD assumes
has already been solved.

Adjacent tools do not fill the gap:

- **Velero / OADP** (already run on this estate per `project_oadp`) backs up
  resources to object storage for *disaster recovery*. Its output is an opaque
  restore blob, not reviewable, git-trackable manifests.
- **`oc adm must-gather`** produces a diagnostics dump, not re-appliable config.
- **`crane` (Konveyor)** exports workloads for cluster-to-cluster *migration*,
  shaped around per-namespace application bundles, not cluster-wide config CRs.
- **`argocd app diff`** only sees resources already declared in an Application.

What is missing is a **config-capture** ("reverse GitOps") step: scan a running
cluster, separate human-intended custom configuration from operator-generated and
defaulted state, normalize it into clean manifests, and *propose* it for inclusion
in this repo — without ever letting the cluster write directly to the source of
truth.

### Constraints

1. **Git must remain authoritative.** The tool may only ever *propose* config via
   a reviewed PR. It must never push to `main`, and a cluster must never be able
   to mutate the source of truth without human review. This preserves the
   flywheel invariant that ADR-0005 depends on.
2. **Signal, not noise.** An OpenShift cluster holds thousands of objects; the
   overwhelming majority are operator-generated, owned, or default-valued.
   A dump of everything is worse than useless. The tool's value is its *filter*.
3. **Re-appliable output.** Captured objects carry server-side cruft (`status`,
   `managedFields`, `resourceVersion`, `uid`, `creationTimestamp`,
   `generation`, default-injected `spec` fields, the
   `kubectl.kubernetes.io/last-applied-configuration` annotation). These must be
   stripped so the result is a clean manifest a human would have written.
4. **Least privilege, but cluster-wide read.** Identifying custom config requires
   reading cluster-scoped config CRs and most namespaces. This is broad read
   access; it must be read-only, and any git credential must be scoped to a fork
   or PR-only token, never a repo-write bot on `main`.
5. **Secrets must not leak.** `Secret` data must never be written to git in clear
   text. Captured secrets are routed through the existing sealed-secrets workflow
   (`sources/sealed-secrets`) or excluded entirely, never emitted raw.

## Decision

Introduce a **config-harvester** workload that runs in-cluster, scans for custom
configuration using a heuristic filter, normalizes it into the `sources/<app>`
layout, and opens a pull request against this repo for human review. It lives as
`sources/config-harvester/` and is delivered like any other app via the
app-of-apps ApplicationSet.

### Detection: heuristic filter

A resource is treated as **candidate custom config** when it survives all of the
following filters. No install baseline is required — the heuristics work against
any running cluster, which is what the bootstrapping use case needs.

1. **Ownership** — skip any object with non-empty `metadata.ownerReferences`.
   Owned objects are reconciled by a controller and belong to whatever created
   them, not to a human.
2. **Field manager** — inspect `metadata.managedFields`. Keep objects whose
   `spec`-owning manager indicates human or client origin (`kubectl`, `oc`,
   `argocd`, the console's `Mozilla`/`openshift-console` managers). Skip objects
   whose fields are owned exclusively by an operator or controller service
   account.
3. **Namespace scope** — deny-list churny system namespaces (`kube-*`,
   `openshift-*`) by default, with a curated **allow-list of exceptions** where
   real cluster config legitimately lives (`openshift-config`,
   `openshift-config-managed`, `openshift-monitoring` user overrides, etc.).
   User-created namespaces pass by default.
4. **Curated config GVK (Group/Version/Kind) set** — always-include singleton, user-tunable
   cluster-config CRs regardless of namespace heuristics, because these are the
   highest-value config and are known by kind. The `config.openshift.io` group
   (`Ingress`, `OAuth`, `Image`, `Scheduler`, `Network`, `APIServer`,
   `Proxy`, `Console`, ...), plus `MachineConfig`, `Tuned`, `ContainerRuntimeConfig`,
   `KubeletConfig`, and console customization CRs.
   - **Named singletons in denied namespaces.** The same always-include logic
     extends to specific high-value objects known by **(namespace, name)** that live
     in an otherwise-denied namespace and carry no human field-manager — they bypass
     both the namespace deny-list (filter 3) and the field-manager filter (filter 2),
     but not the ownership/Argo filters. The canonical case is
     **`kube-system/cluster-config-v1`**, the installer's stored `install-config`
     (cluster identity/provenance: `baseDomain`, networking, platform, topology).
     This object is **provenance, not reconciled config** — nothing controls it, and
     it must **not** be driven by Argo CD — and it is **cluster-specific**. It is
     therefore captured *outside* `sources/` entirely, under
     **`clusters/<cluster-name>/cluster-config/`** (see Output placement), not as a
     shared app. A future cluster-install / bootstrap app may adopt it; until then it
     is a per-cluster captured record.
   - **Embedded-secret caveat.** A `ConfigMap` can carry secret material in its
     `data`, which the `Secret`-kind routing (constraint 5) does not catch. For
     `cluster-config-v1` this is safe — the installer blanks `pullSecret` and the
     `sshKey` is a public key — but any curated named object must be secret-audited
     before it is added to the always-include set.
5. **Already-managed exclusion** — skip anything Argo CD already manages
   (objects carrying the `app.kubernetes.io/instance` / Argo tracking label or
   annotation). The harvester's job is to find what is *not yet* in the flywheel.

The GVK (Group/Version/Kind) set, namespace allow-list, and field-manager allow-list are configuration
of the harvester itself, carried in `sources/config-harvester/` so the heuristics
are auditable and tunable by PR. They start permissive-toward-skipping (false
negatives — missing a custom object — are cheap to fix later; false positives
that dump operator noise erode trust in the tool).

### Confidence ranking: temporal signal (advisory, heuristic 6)

The five filters above decide *whether* an object is a candidate. A sixth signal —
**time** — does not gate; it **ranks and annotates** the survivors so a reviewer's
attention goes to the most-likely-human config first. It is deliberately never an
include/exclude filter, because the failure modes below are too noisy to gate on.

Two temporal inputs, in order of strength:

1. **Last human edit (`managedFields` time).** Each `managedFields` entry carries a
   per-manager `time`. When a *human* field-manager (`kubectl`/`oc`/console) is
   recorded as having touched `spec`/`data`, that timestamp is the most direct
   evidence of human intent — and, unlike `creationTimestamp`, it survives operator
   delete/recreate. This is high-precision but **low-recall**: a cluster built by
   operators/Helm/GitOps often has no human edit-times at all (the Phase-0 run found
   zero), so its *absence* means nothing.
2. **Install cohort (`creationTimestamp − t0`).** Most platform/install objects are
   created in a window around cluster bootstrap. An object born in that window is
   *more likely* install baseline; one born well after is *more likely* config a
   human added over the cluster's life. The reference epoch `t0` is anchored on
   install **start** (earliest of ClusterVersion's first-history `startedTime` and
   the `kube-system` namespace creationTimestamp) — **not** CVO completion, since
   day-1 config (MachineConfigs, `config.openshift.io` CRs) is written *during*
   bootstrap and would otherwise read as pre-install.

These combine into an advisory confidence (`high`/`medium`/`low`) surfaced in the PR
body, never written into the emitted manifest. Three properties keep it honest:

- **It never excludes.** Day-1 *human* config (custom chrony/NTP, SSH MachineConfigs,
  the cluster config singletons) lands in the install cohort too — gating on cohort
  would discard exactly the config the harvest exists to capture. `low` means
  "probably install baseline, look here last," not "drop."
- **It does not resolve the operator-rendered-vs-authored ambiguity** (the class-(2)
  noise this ADR already flags): MCO-rendered MachineConfigs appear both inside and
  outside the cohort. Timestamps narrow attention; only a baseline diff separates
  rendered from authored.
- **`creationTimestamp` reflects API create time, not intent** — operators recreate
  objects continuously (cert rotation, upgrades) — which is precisely why this is a
  ranking signal feeding a human, not a filter.

### Normalization

Each surviving object is **neated** before emission:

- Drop `status`.
- Drop `metadata.managedFields`, `resourceVersion`, `uid`, `creationTimestamp`,
  `generation`, `selfLink`.
- Drop the `kubectl.kubernetes.io/last-applied-configuration` annotation and
  other tool-injected annotations.
- Drop default-injected `spec` fields where determinable.
- Emit one document per object with a generated/updated `kustomization.yaml`.

### Output placement

Most captured objects land in the standard `sources/<app-name>/` layout (ADR-0001),
because most captures are intended for Argo CD to reconcile. The `<app-name>` is
derived, not chosen. The exception is captured **provenance that must not be
Argo-reconciled** (below), which is placed per-cluster outside `sources/`:

- **Namespaced resources** map to `sources/<app-name>/` where `<app-name>` is the
  resource's **OpenShift Project (namespace) name**. A namespace and its config
  are one deployable unit, so the namespace name is the natural app name (e.g.
  resources in the `samba` namespace → `sources/samba/`).
- **Cluster-scoped config** maps to the existing app that owns that config domain
  (e.g. `OAuth`/`Authentication` → `sources/openshift-authentication/`,
  `ClusterVersion` → `sources/cluster-version/`). A small domain→app table in the
  harvester config handles these; unmapped cluster config falls to a review-only
  bucket rather than guessing.
- **Cluster-specific provenance** (the curated named singletons of heuristic 4,
  e.g. `cluster-config-v1`) is **not** an Argo source. It is placed under
  **`clusters/<cluster-name>/cluster-config/`**, deliberately outside `sources/` so
  the app-of-apps ApplicationSet never turns it into a reconciled Application —
  this config records how a specific cluster was *installed*; Argo CD must not drive
  it. It is cluster-specific (the cluster name is part of the path) and is captured
  for the record, not for reconciliation. If/when a cluster-install or bootstrap app
  exists, that provenance may be adopted into it; until then this is its home.
- **Update-or-create.** If the target directory already exists, the harvest is an
  **update** to it — the object is merged in and any `kustomization.yaml` extended,
  never a parallel app. A new directory is created only when none exists yet for that
  Project/domain/cluster. This means re-harvesting already-captured config surfaces
  as a reviewable diff, not a duplicate.

`Secret` objects are never emitted raw. A captured `Secret` is either routed
through `sources/sealed-secrets` (sealed before commit) or listed in the PR body
as "found, excluded — seal manually," depending on configuration. The default is
to exclude and report.

### Output: pull request

The harvester writes to a working branch and opens a PR via `gh` against this
repo. It never pushes to `main`. The PR is the review gate: a human inspects the
proposed manifests, confirms they are correct and complete, and merges — at which
point Argo CD adopts the resources and the cluster config is, from then on,
git-managed. The PR body summarizes what was captured, what was skipped and why,
and flags any excluded secrets.

The git credential is a **PR-only token** (fork-and-PR or a token without
push-to-protected-branch rights), satisfying ADR-0008 branch protection — the
in-cluster workload structurally *cannot* bypass review.

### Workload shape

`sources/config-harvester/` is a Kustomize source containing:

```
sources/config-harvester/
  kustomization.yaml
  cronjob.yaml              # scheduled harvest; also runnable ad-hoc
  rbac.yaml                 # ServiceAccount + cluster-scoped read-only ClusterRole
  config.yaml              # ConfigMap: GVK (Group/Version/Kind) set, namespace + manager allow-lists
  README.md
```

The ClusterRole is read-only (`get`/`list`/`watch`) cluster-wide. The git/`gh`
token is supplied as a sealed secret. The job runs on a schedule (weekly is a
sane default — drift accumulates slowly) and can be triggered on demand for the
initial k8s-sno import. It is delivered to a cluster by the presence of
`clusters/<cluster>/config-harvester.yaml`, like every other app.

## Consequences

**Positive:**

- Closes the documented roadmap gap: existing k8s-sno config can be imported into
  the flywheel mechanically instead of hand-transcribed, and future ad-hoc edits
  on any cluster surface as proposed PRs rather than silent drift.
- The flywheel invariant is preserved by construction — the cluster can only
  *propose*, never write source-of-truth. ADR-0005 and ADR-0008 hold.
- Output lands in the existing `sources/<app>` layout, so captures merge into the
  right app directory and are immediately consumable by Argo CD (and Ansible /
  PolicyGenerator, per ADR-0001) with no reorganization.
- General-purpose: nothing about the heuristics is k8s-sno-specific, so the same
  workload serves every current and future cluster.

**Negative / constraints:**

- Heuristic detection is inherently imperfect. It will miss some custom config
  (false negatives) and occasionally propose operator noise (false positives).
  The PR review gate absorbs this, but the allow-lists need ongoing tuning, and
  early PRs will be noisier until the lists are refined.
- Without a baseline diff, the tool cannot know which `spec` fields are
  user-set versus API-defaulted with certainty; neating is best-effort and a
  reviewer must still read the diff.
- Broad cluster-wide read access is a meaningful privilege grant. It is read-only
  and the git token is PR-scoped, but the workload still sees (and must carefully
  *not* emit) secret material.
- This is net-new tooling to maintain. The neating/filter logic is non-trivial and
  overlaps in spirit with `kubectl-neat` and `crane`; a future revision may choose
  to wrap an existing tool rather than carry bespoke logic.
- It does not replace OADP. OADP remains the disaster-recovery backup; the
  harvester captures *intent* for git, not *state* for restore. The two are
  complementary.

## Related

- ADR-0001: Sources organized by application
- ADR-0005: Flywheel self-reference
- ADR-0008: Branch protection and repository governance
- Project roadmap: import existing k8s-sno configuration into the flywheel
- `sources/sealed-secrets/`, `sources/oadp/`
- [Argo CD: why GitOps is one-directional](https://argo-cd.readthedocs.io/en/stable/)
