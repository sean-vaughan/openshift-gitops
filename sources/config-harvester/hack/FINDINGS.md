# config-harvester — Phase 0 findings

Prototype scan run against `k8s-sno` (live, read-only) on 2026-06-16.
See ADR-0011 for the design this validates.

## Result

The heuristic filter works and the tuning loop converges:

| Iteration | Change | Candidates | Signal |
|-----------|--------|-----------:|-------:|
| 1 | owner + system-ns + argo filters | 394 | 9.6% |
| 2 | require proven human field-manager in system ns | 309 | 7.5% |
| 3 | deny known auto-propagated per-namespace objects | **87** | **2.1%** |

Out of **4109** objects considered, 87 survived as capture candidates. Neating
produces clean, re-appliable manifests (verified: `status`, `managedFields`,
`uid`, `resourceVersion`, `ownerReferences` all stripped).

## What the filter got right

The 87 survivors include the genuinely-custom config a human would want in git:

- **Cluster config singletons** — `ingresses/oauths/networks/schedulers/proxies/
  dnses.config.openshift.io/cluster`
- **Custom MachineConfigs** — `50-*-chrony-configuration` (custom NTP pools),
  `50-master-dnsmasq-configuration`, `99-{master,worker}-ssh`
- **KubeletConfigs** — `set-kubelet-parameters-{master,worker}`
- **App config** — `vector-config -n syslog-test`, `frame-aggregator`,
  `pvc-autosize-cron`, `consolelink/argocd`, `assisted-installer-network-policy`

## The two irreducible noise classes (this is the important finding)

Tuning removed ~80% of the noise, but two classes remain that heuristics alone
**cannot** cleanly resolve — exactly the risk ADR-0011 names:

1. **Operator-created-but-unowned RBAC.** The OpenShift/OCM operators create
   `Role`/`RoleBinding` objects (`open-cluster-management:*`,
   `system:image-builders`, namespace `admin`) with no `ownerReference` and no
   operator field-manager. They are noise, but only a name/prefix denylist
   removes them — and that list is open-ended and cluster-dependent.

2. **Operator-RENDERED vs human-authored MachineConfigs.** `97-/98-*-generated-
   kubelet` and `00-*-generated-crio` are renderings the MCO produces from a
   `KubeletConfig`/`ContainerRuntimeConfig`; `50-*` and `99-*` are typically
   human-authored. They are structurally identical — same kind, no owner, same
   managers. Capturing the rendered ones would put derived state in git that
   fights the operator. **Distinguishing them reliably requires a baseline
   diff**, which the heuristic-only approach does not have.

## Temporal signal (heuristic 6) — added 2026-06-18

Re-ran with the advisory temporal signal (ADR-0011 heuristic 6): an **install
cohort** from `creationTimestamp − t0`, plus a **last-human-edit** time from
`managedFields`. It ranks/annotates candidates; it does **not** gate. On the same 88
candidates:

| Confidence | Count | Meaning |
|------------|------:|---------|
| high (human edit-time present) | **0** | a human field-manager touched spec/data, with a timestamp |
| medium (created well after install) | **70** | added over the cluster's life — more likely later human config |
| low (install cohort) | **18** | born at bootstrap — config CRs, chrony/ssh/dnsmasq MCs, assisted-installer |

Three findings, each a tuning lesson:

1. **Anchor t0 on install *start*, not CVO completion.** First cut used
   ClusterVersion `completionTime`; day-1 objects are written *during* bootstrap, so
   they showed as created ~1 day *before* t0 and missed the cohort. Re-anchoring to
   the earliest of (ClusterVersion first-history `startedTime`, `kube-system` ns
   creationTimestamp) fixed it — 18 cohort hits, all correct. Window widened to 6h.
2. **Cohort ≠ "drop".** Several cohort objects (`50-masters-chrony-configuration`,
   `99-master-ssh`, the `*.config.openshift.io/cluster` singletons) are exactly the
   human-intended config we *want* to capture — they just landed at install. This is
   the concrete proof the signal must stay advisory, never a filter.
3. **It does not resolve class (2) by itself.** `98-*-generated-kubelet` (cohort) and
   `97-*-generated-kubelet` (+399d) — both MCO renderings — fall on opposite sides of
   the boundary. Timestamps narrow reviewer attention; only a baseline diff cleanly
   separates rendered from authored.
4. **The high-precision signal is sparse here** (high=0): on a cluster built by
   operators/Helm/GitOps, `managedFields` human edit-times are rare. When present
   it's gold; you cannot rely on its presence.

Net: the signal earns its keep as a **reviewer-attention ranking** in the PR body
(sort `medium`/`high` to the top, label `low` as probable-install-baseline), not as
a filter. Candidate count is unchanged (88) by design.

## Conclusion → decision input for Phase 1+

- **The core value is real.** A 2.1% signal ratio on a busy cluster, surfacing
  the right cluster config and custom MachineConfigs, is a useful harvest.
- **It cannot be fully autonomous.** Classes (1) and (2) mean a human must review
  before anything lands in git. This *validates* the PR-review gate in ADR-0011
  — and it is a strong, concrete argument for the **console plugin** (the review
  UX) being worth building, not gold-plating.
- **A baseline-diff mode is the highest-value next refinement** (beyond Phase 0).
  Comparing against a fresh-install reference would resolve class (2) and shrink
  the candidate set further. It was deferred in ADR-0011 as "needs a maintained
  baseline"; these findings suggest it earns its keep.

## Running it

```sh
./harvest_scan.py                 # report only
./harvest_scan.py --emit ./out    # also write neated manifests
./harvest_scan.py --show-skips    # explain every skip
```

Read-only; requires `oc` logged in. This is throwaway Phase-0 validation code —
the production logic is the Go controller in Phase 1, not this script.
