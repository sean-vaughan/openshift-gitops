# App-of-Apps Internals

> **Zoom level:** Mechanism — how the ApplicationSet generates Applications.
> **Previous:** [← Cluster Architecture](02-cluster-architecture.md) | **Next:** [Configuration Cascade →](04-configuration-cascade.md)

The ApplicationSet uses a **matrix generator**: a list of clusters × a git file
scanner over `clusters/<clusterName>/*.yaml`. Each combination of (cluster, gate
file) produces one Argo CD Application.

```mermaid
%%{init: {'flowchart': {'curve': 'step', 'padding': 20}}}%%
flowchart TD
    classDef git      fill:#e3f2fd,stroke:#1565c0,color:#000
    classDef argo     fill:#fff8e1,stroke:#e65100,color:#000
    classDef platform fill:#eceff1,stroke:#546e7a,color:#000
    classDef appteam  fill:#e8f5e9,stroke:#2e7d32,color:#000
    classDef override fill:#fff3e0,stroke:#ef6c00,color:#000

    subgraph GIT["openshift-gitops (git)"]
        direction LR
        ELEMENTS["clusters/k8s-sno/\napp-of-apps/\nkustomization.yaml\n\nelements:\n  - clusterName: k8s-sno"]:::git
        GATE_AO["clusters/k8s-sno/\napp-of-apps.yaml\n\nspec:\n  source:\n    path: clusters/k8s-sno/app-of-apps"]:::override
        GATE_AP["clusters/k8s-sno/\napp-projects.yaml\n\nspec:\n  source:\n    helm:\n      valueFiles: [platform.yaml]"]:::override
        GATE_X["clusters/k8s-sno/\nmy-app.yaml\n\n{} ← all defaults"]:::git
        SOURCES["sources/{app}/\n«app configs»"]:::git
    end

    subgraph APPSET["«argo-appset» app-of-apps"]
        direction TB
        GEN_LIST["list generator\n\nclusterName: k8s-sno"]:::argo
        GEN_GIT["git files generator\n\nclusters/k8s-sno/*.yaml"]:::argo
        MATRIX["matrix\n(cartesian product)"]:::argo
        TEMPLATE["template\n\nname: k8s-sno---{project}---{app}\ndest: k8s-sno\nsource: sources/{app}\nsyncPolicy: automated"]:::argo
        PATCH["templatePatch\n\nmerges gate file\nmetadata + spec\non top of template"]:::argo
    end

    APPS_AO["«argo-app»\nk8s-sno---platform---app-of-apps\n\nsource → clusters/k8s-sno/app-of-apps/\nprune: false, selfHeal: false"]:::override
    APPS_AP["«argo-app»\nk8s-sno---platform---app-projects\n\nsource → sources/app-projects/chart\nhelm.valueFiles: platform.yaml"]:::platform
    APPS_X["«argo-app»\nk8s-sno---platform---my-app\n\nsource → sources/my-app\nall org defaults"]:::git

    ELEMENTS  --> GEN_LIST
    GATE_AO   --> GEN_GIT
    GATE_AP   --> GEN_GIT
    GATE_X    --> GEN_GIT
    GEN_LIST  --> MATRIX
    GEN_GIT   --> MATRIX
    MATRIX    --> TEMPLATE
    TEMPLATE  --> PATCH
    PATCH     --> APPS_AO
    PATCH     --> APPS_AP
    PATCH     --> APPS_X
    SOURCES   --> APPS_X
```

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
