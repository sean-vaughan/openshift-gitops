# clusters/k8s-sno

Lab / development Single Node OpenShift cluster.

Free-form name (lab cluster, per ADR-0007). Future production clusters use the
`<dc>-<type>-<env>-<n>` pattern.

## Bootstrap

```bash
kubectl apply -k clusters/k8s-sno/app-of-apps/
```

## Apps deployed to this cluster

| Gate file | Source | Notes |
|---|---|---|
| [`app-of-apps.yaml`](app-of-apps.yaml) | `clusters/k8s-sno/app-of-apps/` | Self-managing ApplicationSet |
| [`app-projects.yaml`](app-projects.yaml) | `sources/app-projects/` | AppProject definitions |
