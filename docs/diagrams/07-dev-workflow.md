# Development Workflow

> **Zoom level:** Process — inner loop and environment promotion.
> **Previous:** [← Bootstrap Sequence](06-bootstrap.md)
> **ADR:** [ADR-0006 — Development workflow and environment promotion](../adr/0006-development-workflow-and-environment-promotion.md)

## Inner development loop

The loop is intentionally cluster-first. Git operations enter only when a
configuration is proven and worth keeping.

```mermaid
%%{init: {'flowchart': {'curve': 'step', 'padding': 20}}}%%
flowchart LR
    classDef idea    fill:#fff9c4,stroke:#f9a825,color:#000
    classDef cluster fill:#e8f5e9,stroke:#2e7d32,color:#000
    classDef git     fill:#e3f2fd,stroke:#1565c0,color:#000
    classDef argo    fill:#fff8e1,stroke:#e65100,color:#000

    IDEA["💡 Have an idea"]:::idea
    TRY["🖥️ Try on cluster\n\nArgo CD UI\noc apply / kubectl\nhelm install\n\n(no git required)"]:::cluster
    WORKS{"Does it\nwork?"}
    COMMIT["📝 Commit to\nsources/<app>/\nfeature branch\n\n(capture what works)"]:::git
    GATE["🔗 Add gate file\nclusters/<cluster>/<app>.yaml\n\n(when ready for\ncontinuous reconciliation)"]:::argo
    DONE["✅ Argo CD\nreconciles it\nforever"]:::argo

    IDEA  --> TRY
    TRY   --> WORKS
    WORKS -->|"no — iterate"| TRY
    WORKS -->|"yes"| COMMIT
    COMMIT --> GATE
    GATE  --> DONE
```

## Environment promotion

Each environment has a different relationship to git history. Promotion is always
a deliberate upward step — never automatic from dev to prod.

```mermaid
%%{init: {'flowchart': {'curve': 'step', 'padding': 20}}}%%
flowchart LR
    classDef dev  fill:#e8f5e9,stroke:#2e7d32,color:#000
    classDef test fill:#e3f2fd,stroke:#1565c0,color:#000
    classDef prod fill:#fce4ec,stroke:#c62828,color:#000
    classDef git  fill:#fff8e1,stroke:#e65100,color:#000

    FB["feature\nbranch"]:::git
    MAIN["main\nbranch"]:::git
    TAG["semver\ntag v1.2.0"]:::git

    subgraph DEV["dev clusters\nrdu-*-dev-*"]
        DEV_APP["targetRevision:\nfeature/my-branch\nor HEAD"]:::dev
    end

    subgraph TEST["test clusters\nrdu-*-tst-*"]
        TEST_APP["targetRevision:\nHEAD"]:::test
    end

    subgraph PROD["prod clusters\nrdu-*-prd-*"]
        PROD_APP["targetRevision:\nv1.2.0"]:::prod
    end

    FB   -->|"track branch\n(inner loop)"| DEV_APP
    FB   -->|"merge PR\n→ auto promotes"| MAIN
    MAIN -->|"track HEAD"| TEST_APP
    MAIN -->|"cut tag\n(explicit release)"| TAG
    TAG  -->|"update gate file\ntargetRevision"| PROD_APP
```

## Changing targetRevision

Any Application's `targetRevision` can be changed in three ways:

| Method | Scope | Persists across sync? |
|---|---|---|
| Gate file override | This app on this cluster | Yes (committed to git) |
| Argo CD UI override | This app instance | Yes — `ignoreApplicationDifferences` preserves it |
| Kustomize patch on `app-of-apps` | All apps on this cluster | Yes (committed to git) |

## Team-controlled repos

A team that wants full control of their revision can point a gate file at their
own git repo. They inherit all org defaults (project, sync policy, destination)
and only override the source:

```yaml
# clusters/rdu-sno-dev-1/my-team-apps.yaml
spec:
  source:
    repoURL: https://github.com/my-team/apps.git
    targetRevision: HEAD
    path: sources/my-team-apps
```

This is a first-class supported pattern — see ADR-0006.
