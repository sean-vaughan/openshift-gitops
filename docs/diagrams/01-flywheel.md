# The Flywheel

> **Zoom level:** Conceptual — one idea per box.
> **Next:** [Cluster Architecture →](02-cluster-architecture.md)

The simplest statement of the architecture: git is the source of truth; the
ApplicationSet is the engine that turns git state into running Kubernetes objects;
the flywheel spins continuously, reconciling drift back to desired state.

```mermaid
%%{init: {'flowchart': {'curve': 'step', 'padding': 20}}}%%
flowchart LR
    classDef git      fill:#e3f2fd,stroke:#1565c0,color:#000
    classDef argo     fill:#fff8e1,stroke:#e65100,color:#000
    classDef platform fill:#eceff1,stroke:#546e7a,color:#000
    classDef appteam  fill:#e8f5e9,stroke:#2e7d32,color:#000
    classDef cluster  fill:#f5f5f5,stroke:#9e9e9e,color:#000

    %% ── Source of truth ──────────────────────────────────────────────
    subgraph REPO["openshift-gitops (git)"]
        direction TB
        GATES["clusters/{cluster}/{app}.yaml\n«gate files + overrides»"]:::git
        SOURCES["sources/{app}/\n«app configs»"]:::git
        PROFILES["profiles/\n«team + cluster-type defaults»"]:::git
    end

    %% ── Engine ───────────────────────────────────────────────────────
    subgraph TOOLS["«tools cluster»"]
        direction TB
        APPSET["«argo-appset»\napp-of-apps\n\nmatrix:\n  cluster list\n  × gate files"]:::argo
        APPS["«argo-apps»\n{cluster}---{project}---{app}"]:::argo
    end

    %% ── Output ───────────────────────────────────────────────────────
    subgraph TARGET["«managed cluster»"]
        PLT["«k8s objects»\nplatform configs"]:::platform
        APP["«k8s objects»\napp-team configs"]:::appteam
    end

    %% ── Flow ─────────────────────────────────────────────────────────
    GATES   -->|"gates which apps\nrun on which cluster"| APPSET
    APPSET  -->|"generates one Application\nper gate file"| APPS
    SOURCES -->|"app source content"| APPS
    APPS    -->|"continuously\nreconciles"| PLT
    APPS    -->|"continuously\nreconciles"| APP
```

## Key properties

- **Gate file present + empty** → app runs with all org defaults.
- **Gate file present + overrides** → org defaults merged with per-cluster overrides.
- **Gate file absent** → app does not run on that cluster.
- **Drift** → Argo CD detects and reconciles back to git state within minutes.
- **Self-managing** → the ApplicationSet is itself an Argo CD Application, so
  changes to the ApplicationSet are also reconciled from git (see [Bootstrap →](06-bootstrap.md)).
