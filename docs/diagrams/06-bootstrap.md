# Bootstrap Sequence

> **Zoom level:** Operations — first-time cluster setup.
> **Previous:** [← Ownership Model](05-ownership.md) | **Next:** [Development Workflow →](07-dev-workflow.md)
> **ADR:** [ADR-0005 — Flywheel self-reference and bootstrapping seams](../adr/0005-flywheel-self-reference.md)

The flywheel is self-managing once running, but something must turn it the first
time. These are the intentional bootstrapping seams — the one-time manual steps
that break the self-reference cycle.

```mermaid
sequenceDiagram
    actor OPS as Operator
    participant GIT as git repo
    participant K8S as cluster (k8s-sno)
    participant ARGO as Argo CD

    Note over OPS,K8S: Step 1 — Manual bootstrap (one-time)
    OPS->>GIT: commit clusters/k8s-sno/app-of-apps/
    Note right of GIT: cluster-secret.yaml<br/>kustomization.yaml<br/>(patches elements list)
    OPS->>K8S: kubectl apply -k clusters/k8s-sno/app-of-apps/
    K8S-->>ARGO: ApplicationSet created
    K8S-->>ARGO: cluster secret k8s-sno registered

    Note over ARGO,K8S: Step 2 — Flywheel starts spinning
    ARGO->>GIT: poll clusters/k8s-sno/*.yaml
    GIT-->>ARGO: app-of-apps.yaml, app-projects.yaml, …
    ARGO->>ARGO: generate Applications from gate files
    ARGO->>K8S: sync app-of-apps Application
    Note right of K8S: ApplicationSet now self-managed
    ARGO->>K8S: sync app-projects Application
    Note right of K8S: AppProjects created (platform, …)

    Note over ARGO,K8S: Step 3 — Steady state
    ARGO->>K8S: sync all other Applications
    Note right of K8S: All apps reach Healthy/Synced
    loop Continuous reconciliation
        ARGO->>GIT: poll for changes
        GIT-->>ARGO: new commit detected
        ARGO->>K8S: reconcile drift to desired state
    end
```

## Self-reference map

Every self-reference in the repo is intentional and documented. Each has a single
manual bootstrapping seam that breaks the cycle once.

```mermaid
%%{init: {'flowchart': {'curve': 'step', 'padding': 20}}}%%
flowchart LR
    classDef argo     fill:#fff8e1,stroke:#e65100,color:#000
    classDef platform fill:#eceff1,stroke:#546e7a,color:#000
    classDef manual   fill:#fce4ec,stroke:#c62828,color:#000

    MANUAL["🔑 kubectl apply -k\nclusters/k8s-sno/app-of-apps/\n\n(one-time manual step)"]:::manual

    APPSET["«argo-appset»\napp-of-apps"]:::argo
    APP_AO["«argo-app»\nk8s-sno---platform---app-of-apps\n\nprune: false\nselfHeal: false"]:::argo
    SECRET["«Secret»\nk8s-sno-cluster\n\nargocd.argoproj.io/secret-type: cluster"]:::platform
    APP_AP["«argo-app»\nk8s-sno---platform---app-projects"]:::argo
    PROJ["«AppProject»\nplatform"]:::platform
    ALL_APPS["all other\n«argo-apps»"]:::argo

    MANUAL -->|"delivers both\nin one apply"| APPSET
    MANUAL -->|"delivers both\nin one apply"| SECRET
    SECRET -->|"enables Argo CD to\ngenerate Applications\nfor k8s-sno"| APPSET
    APPSET -->|generates| APP_AO
    APP_AO -->|"self-manages\nApplicationSet"| APPSET
    APPSET -->|generates| APP_AP
    APP_AP -->|creates| PROJ
    PROJ   -->|"AppProject exists\nbefore apps need it"| ALL_APPS
    APPSET -->|generates| ALL_APPS
```

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
