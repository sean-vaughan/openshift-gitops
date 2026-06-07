# ADR-0004: Always use named Argo CD cluster secrets; never use `in-cluster`

- **Status**: Accepted
- **Date**: 2026-06-03

## Context

Argo CD provides a built-in cluster destination named `in-cluster` that refers to
the cluster where Argo CD itself is running, with the server address
`https://kubernetes.default.svc`. Using this convenience shortcut is tempting for
per-cluster Argo CD deployments where there is only one destination cluster.

However, `in-cluster` has several problems:

1. **Naming is wrong from day one.** Application names in this repo include the
   cluster name (`<clusterName>---<project>---<app>` per ADR-0002). If the cluster
   is referred to as `in-cluster`, all Application names use that generic string
   instead of the actual cluster identity. Migrating to the real name later requires
   renaming every Application and every gate file.

2. **Hub migration is harder.** When a hub Argo CD instance manages the cluster
   remotely, `in-cluster` is no longer valid — it refers to the hub cluster, not the
   target. A named cluster secret with the correct server URL can be updated in one
   place; every Application referencing `in-cluster` must be changed.

3. **Observability is degraded.** The Argo CD UI, `kubectl`, and alerting tools
   all surface the cluster name. `in-cluster` provides no signal about which cluster
   is being operated.

4. **Inconsistency with multi-cluster deployments.** The app-of-apps pattern in
   this repo treats all clusters uniformly. `in-cluster` is a special case that
   breaks the uniform model.

## Decision

Every cluster managed by Argo CD is represented by a named `Secret` of type
`argocd.argoproj.io/secret-type: cluster`. The secret name and the `stringData.name`
field use the actual cluster name (matching the RHACM `ManagedCluster` name). The
`in-cluster` destination is never used.

For a cluster running its own Argo CD instance, the server URL is still
`https://kubernetes.default.svc` — but the name is the real cluster name:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: <clusterName>-cluster
  namespace: openshift-gitops
  labels:
    argocd.argoproj.io/secret-type: cluster
    app.kubernetes.io/instance: app-of-apps
  annotations:
    managed-by: argocd.argoproj.io
stringData:
  name: <clusterName>
  server: 'https://kubernetes.default.svc'
type: Opaque
```

The cluster secret lives at `clusters/<clusterName>/app-of-apps/cluster-secret.yaml`
and is deployed as part of the Kustomize overlay that also patches the ApplicationSet
cluster list (see ADR-0003 and `clusters/<clusterName>/app-of-apps/kustomization.yaml`).

The ApplicationSet `elements` list uses the real cluster name:

```yaml
- list:
    elements:
      - clusterName: <clusterName>
```

## Consequences

**Positive:**

- Application names are correct and stable from the first deployment.
- Hub migration is a server URL update in the cluster secret — no Application or
  gate file changes required.
- The Argo CD UI, dashboards, and alerts always show the real cluster name.
- The cluster list in the ApplicationSet and the cluster secret are always
  consistent — both use the same name.

**Negative / constraints:**

- One additional file is required at cluster bootstrap time: the cluster secret
  must be applied before the ApplicationSet can generate Applications for that
  cluster. This is an intentional bootstrapping seam (see ADR-0005).
- Cluster names must be agreed upon before bootstrapping. Renaming a cluster after
  the fact requires renaming all gate files and all Applications.

## Related

- ADR-0002: Application naming convention
- ADR-0003: Organizational defaults over boilerplate
- ADR-0005: Flywheel self-reference and bootstrapping seams
- `clusters/<clusterName>/app-of-apps/cluster-secret.yaml`
