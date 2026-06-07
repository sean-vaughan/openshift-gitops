# clusters/

Per-cluster gate files and Application overrides.

Each subdirectory `clusters/<clusterName>/` controls one cluster. The cluster name
follows the `<dc>-<type>-<env>-<n>` pattern (ADR-0007), e.g. `rdu-sno-dev-1`.
Lab clusters may use free-form names (e.g., `k8s-sno`).

## Gate files

`clusters/<clusterName>/<app>.yaml` — touching this file deploys `sources/<app>`
to the cluster. The file may be empty (`{}`) to accept all org defaults, or contain
any Argo CD Application field overrides:

```yaml
# Minimal — deploys sources/my-app with all org defaults
{}
```

```yaml
# Override source revision to a feature branch (ADR-0006)
spec:
  source:
    targetRevision: feature/my-experiment
```

```yaml
# Point to a team's own repo
spec:
  source:
    repoURL: https://github.com/my-team/apps.git
    targetRevision: HEAD
    path: sources/my-app
```

A missing gate file means the app is **not deployed** to that cluster.

## app-of-apps subdirectory

`clusters/<clusterName>/app-of-apps/` is special — it is a Kustomize overlay
that renders the ApplicationSet with the correct cluster list and cluster secret
for this cluster. See ADR-0005 for the bootstrapping sequence.

## Bootstrap procedure

```bash
# One-time manual step — see ADR-0005
kubectl apply -k clusters/<clusterName>/app-of-apps/
```

After this, the flywheel manages itself.

## Contents

| Cluster | Type | Environment | Notes |
|---|---|---|---|
| [`k8s-sno`](k8s-sno/) | `sno` | dev (lab) | Primary development cluster |
