# App-of-Apps Internals

> **Zoom level:** Mechanism — how the ApplicationSet generates Applications.
> **Previous:** [← Cluster Architecture](02-cluster-architecture.md) | **Next:** [Configuration Cascade →](04-configuration-cascade.md)

The ApplicationSet uses a **matrix generator**: a list of clusters × a git file
scanner over `clusters/<clusterName>/*.yaml`. Each combination of (cluster, gate
file) produces one Argo CD Application.

![App-of-Apps Internals](img/03-app-of-apps.svg)

> Source: [`src/03-app-of-apps.d2`](src/03-app-of-apps.d2) — render with `make` in this directory.

## Gate file anatomy

A gate file may be empty (`{}`) or contain any Argo CD Application field overrides.
The `templatePatch` in the ApplicationSet deep-merges the gate file onto the
org-default template — only fields present in the gate file are overridden.

```
clusters/k8s-sno/
  app-of-apps.yaml        ← overrides source.path (points to kustomize overlay)
  app-projects.yaml       ← overrides source.helm.valueFiles
  rbac.yaml               ← empty {} — deploys sources/rbac with all defaults
  my-app.yaml             ← overrides source.targetRevision for dev testing
  app-of-apps/
    kustomization.yaml    ← Kustomize overlay: patches elements list + cluster secret
    cluster-secret.yaml   ← named Argo CD cluster secret (ADR-0004)
```

## Name derivation

```
gate file path:   clusters/k8s-sno/my-app.yaml
                              ↑           ↑
                         clusterName   appName (trimSuffix ".yaml")

project default:  "platform"  (override with spec.project in gate file)

Application name: k8s-sno---platform---my-app
```

Full override: set `metadata.name` in the gate file to any value.
