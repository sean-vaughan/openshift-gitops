# ADR-0015: Multi-cluster topology — hub-push vs. Argo CD Agent pull-based

- **Status**: Proposed
- **Date**: 2026-06-18

## Context

The `openshift-gitops` app-of-apps model (ADR-0003, ADR-0005) was designed around
a **hub-push** topology: a central Argo CD instance reaches out over the network to
reconcile state onto spoke clusters. This works well when the hub can initiate
connections to every spoke — the common case for a small estate of well-connected
clusters.

Red Hat OpenShift GitOps 1.19 (released January 2026) promoted the **Argo CD Agent**
from Technology Preview (introduced in 1.17) to **General Availability**. The agent
is a small Go binary deployed on each remote cluster. It maintains a mTLS connection
*inbound* to the hub's management plane — the hub never initiates a connection to
the spoke. From the spoke's perspective, only outbound port 443 to the hub is
required; no inbound firewall rules are needed.

Two topologies are now both production-grade:

| | Hub-push | Argo CD Agent (pull-based) |
|---|---|---|
| **Connectivity** | Hub initiates to spoke | Spoke initiates to hub |
| **Firewall requirement** | Hub → spoke reachable | Spoke → hub reachable |
| **Identity** | Hub kubeconfig per spoke | mTLS cert per agent |
| **GA since** | Argo CD origin | OpenShift GitOps 1.19 (Jan 2026) |
| **Credential surface on hub** | One kubeconfig per spoke | No spoke kubeconfig on hub |

The topologies can coexist within one estate: some spokes may use hub-push, others
pull-agent, managed by the same hub Argo CD.

The multi-cluster topology choice also intersects the Genesis first-light wizard
(ADR-0012): a new cluster's connection model is an organizational dimension that
must be captured once and govern ongoing behavior.

### Constraints

1. **Both topologies are Argo CD Application sources.** Neither changes the
   `sources/<app>` layout, gate files, or ApplicationSet structure. Topology affects
   *connectivity*, not the config grammar.
2. **Security posture differs.** Hub-push stores a spoke kubeconfig (or service
   account token) on the hub — a high-value credential if the hub is compromised.
   Pull-agent eliminates that: the hub holds only a CA bundle for mTLS verification,
   not a credential that grants cluster access. For high-security or regulated
   environments, pull-agent is the better posture.
3. **RHACM placement policy is topology-agnostic.** ManagedCluster labels
   (`dc`, `cluster-type`, `env`) drive policy placement regardless of how Argo CD
   connects to the spoke.
4. **Genesis's own multi-cluster scope.** When Genesis operates as the flywheel
   agent (ADR-0012), it must be able to author gate files and profiles for spokes
   regardless of their connection model. The topology choice is therefore a
   first-class configuration dimension, not an afterthought.

## Decision

Genesis uses **hub-push by default** and adopts **Argo CD Agent pull-based topology
as the standard model for spokes that cannot accept inbound connections** from the
hub. The choice is per-cluster, not org-wide, and is captured in the cluster's OKF
`index.md` and gate files.

### Topology selection rules

A cluster should use **pull-agent** when any of the following apply:

- The cluster is at a network edge (telco RAN, factory, retail, branch office) where
  a firewall or NAT prevents hub-initiated connections.
- The cluster is a **disconnected** or **restricted-network** cluster.
- The security posture requires that no spoke kubeconfig be stored on the hub.
- The cluster is a future-production telco spoke where TM Forum Level 4 autonomy
  is a target (consistent with Red Hat's autonomous-networks direction).

A cluster should use **hub-push** when:

- The cluster is directly reachable from the hub (lab SNO, dev, small connected
  fleet).
- The hub is the cluster itself (the hub manages itself, as in the single-SNO case
  today where `k8s-sno` is both hub and only cluster).
- Operational simplicity outweighs the security delta and agent-per-cluster overhead.

Both topologies are managed by the same ApplicationSet; the distinction is captured
in the gate file for each cluster (or the cluster OKF record) as a `topologyModel`
annotation, not as a structural divergence in the repo.

### First-light wizard integration

The first-light wizard (ADR-0012) adds one question to the organizational dimension
survey:

> **Multi-cluster connectivity model?**
>
> - Hub manages itself only (single-cluster, no spokes)
> - Hub-push (hub initiates to spokes — spokes must be reachable)
> - Pull-agent (spokes initiate to hub — hub needs no inbound connectivity to spokes)
> - Mixed (per-cluster choice)

Selecting "pull-agent" or "mixed" materializes an agent-deployment source
(`sources/argocd-agent/`) in the scaffold, following the same delivery pattern as
any other app.

### Credential model per topology

| Topology | What the hub stores | What the spoke stores |
|---|---|---|
| Hub-push | Kubeconfig / SA token per spoke (Secret) | Nothing hub-specific |
| Pull-agent | CA bundle for mTLS verification | Agent cert + hub endpoint |

Both are managed as sealed secrets and delivered via the flywheel. The pull-agent's
credential surface on the hub is strictly smaller, which improves the blast-radius
if the hub is compromised.

### Relationship to Kagenti and SPIFFE (ADR-0012)

The Argo CD Agent uses mTLS for its own transport authentication. This is distinct
from Kagenti/SPIFFE workload identity, which governs the *Genesis agent's* runtime
identity. The two layers are complementary: SPIFFE/Kagenti identifies Genesis; Argo
CD Agent mTLS identifies the per-cluster reconciliation channel. Neither replaces
the other.

## Consequences

**Positive:**

- Pull-agent topology is now GA and production-supported; Genesis can recommend it
  for edge and disconnected cases without treating it as experimental.
- Hub credential surface shrinks to zero for pull-agent spokes — no spoke kubeconfig
  on the hub is a meaningful security improvement for a hub that aggregates many
  clusters.
- Mixed topology is supported natively; Genesis does not need to choose one model
  for the entire estate.
- The first-light wizard captures the choice once, making it a derived property of
  the cluster record rather than tribal knowledge.
- Alignment with Red Hat's autonomous-networks direction (telco edge, RAN) where
  spoke-to-hub connectivity is the norm.

**Negative / constraints:**

- Pull-agent adds a per-spoke workload (`argocd-agent` binary + RBAC + mTLS cert
  rotation) to operate. It is a Red Hat–supported component, but it is still
  another thing to version, upgrade, and monitor.
- Mixed-topology estates require the team to track which clusters use which model;
  the OKF cluster record is the designated home for this, but it must be kept in
  sync.
- Hub-push is the Argo CD default and carries more ecosystem documentation; pull-
  agent is newer and some edge behaviors (webhook triggers, app-set generators that
  fire on cluster events) may behave differently.
- This ADR does not yet address **Genesis's own network reach**: when Genesis runs
  as an agent (ADR-0012), it needs the ability to query live cluster state (the
  harvester's read-only ClusterRole). Whether Genesis reaches spokes directly or
  via the hub API is a separate, unresolved question for pull-agent spokes.

## Related

- ADR-0003: Organizational defaults over boilerplate
- ADR-0005: Flywheel self-reference
- ADR-0012: Agent-owned repository and flywheel governance (first-light wizard;
  Kagenti/SPIFFE identity)
- [What's New in OpenShift GitOps 1.19 — Argo CD Agent GA (Red Hat Developer, 2026-01-12)](https://developers.redhat.com/blog/2026/01/12/whats-new-openshift-gitops-119)
- [Manage Clusters at Scale with the Argo CD Agent (Red Hat blog)](https://www.redhat.com/en/blog/manage-clusters-and-applications-scale-argo-cd-agent-red-hat-openshift-gitops)
- [argoproj-labs/argocd-agent](https://github.com/argoproj-labs/argocd-agent)
- Red Hat RHACM ManagedCluster labels and placement rules
