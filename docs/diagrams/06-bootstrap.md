# Bootstrap Sequence

> **Zoom level:** Operations — first-time cluster setup.
> **Previous:** [← Ownership Model](05-ownership.md) | **Next:** [Development Workflow →](07-dev-workflow.md)
> **ADR:** [ADR-0005 — Flywheel self-reference and bootstrapping seams](../adr/0005-flywheel-self-reference.md)

The flywheel is self-managing once running, but something must turn it the first
time. These are the intentional bootstrapping seams — the one-time manual steps
that break the self-reference cycle.

![Bootstrap Sequence](img/06a-bootstrap-sequence.svg)

> Source: [`src/06a-bootstrap-sequence.d2`](src/06a-bootstrap-sequence.d2) — render with `make` in this directory.

## Self-reference map

Every self-reference in the repo is intentional and documented. Each has a single
manual bootstrapping seam that breaks the cycle once.

![Self Reference Map](img/06b-self-reference.svg)

> Source: [`src/06b-self-reference.d2`](src/06b-self-reference.d2) — render with `make` in this directory.

## Bootstrap checklist

```
□ 1. Cluster name decided and matches ADR-0007 convention
□ 2. clusters/<clusterName>/app-of-apps/cluster-secret.yaml created
□ 3. clusters/<clusterName>/app-of-apps/kustomization.yaml patches elements list
□ 4. openshift-gitops operator already installed on cluster
       (or installed as part of bootstrap via Ansible / ACM policy)
□ 5. kubectl apply -k clusters/<clusterName>/app-of-apps/
□ 6. Wait for app-of-apps Application to reach Healthy
□ 7. Verify app-projects Application synced (AppProjects exist)
□ 8. Verify all gate-file Applications appear and sync
```
