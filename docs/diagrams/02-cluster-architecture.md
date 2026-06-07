# Cluster Architecture

> **Zoom level:** Infrastructure — clusters, Argo CD instances, ACM hub.
> **Previous:** [← The Flywheel](01-flywheel.md) | **Next:** [App-of-Apps Internals →](03-app-of-apps.md)

Two deployment models are supported. Per-cluster is the default; hub is the
enterprise scale-out pattern. The git repo structure and Application naming
convention are identical in both — switching is a generator config change, not a
repo restructure (ADR-0002, ADR-0004).

---

## Model A — Per-cluster Argo CD (default)

Each cluster runs its own Argo CD instance, managing only itself.
The cluster list in the ApplicationSet has exactly one entry.

```mermaid
%%{init: {'flowchart': {'curve': 'step', 'padding': 20}}}%%
flowchart LR
    classDef git      fill:#e3f2fd,stroke:#1565c0,color:#000
    classDef argo     fill:#fff8e1,stroke:#e65100,color:#000
    classDef platform fill:#eceff1,stroke:#546e7a,color:#000
    classDef appteam  fill:#e8f5e9,stroke:#2e7d32,color:#000

    GIT[("openshift-gitops\ngit repo")]:::git

    subgraph SNO["«cluster» k8s-sno"]
        direction TB
        OP["«operator»\nopenshift-gitops"]:::argo
        subgraph ARGOCD["«kind: ArgoCD» platform"]
            APPSET["«argo-appset»\napp-of-apps\nelements:\n  - clusterName: k8s-sno"]:::argo
            APPS_P["«argo-app»\nplatform configs"]:::platform
            APPS_A["«argo-app»\napp-team configs"]:::appteam
        end
        K8S_P["«k8s objects»\nplatform"]:::platform
        K8S_A["«k8s objects»\napp-team"]:::appteam
    end

    GIT      -->|"clusters/k8s-sno/*.yaml"| APPSET
    APPSET   -->|generates| APPS_P
    APPSET   -->|generates| APPS_A
    APPS_P   -->|reconciles| K8S_P
    APPS_A   -->|reconciles| K8S_A
```

---

## Model B — Hub Argo CD (enterprise / multi-cluster)

One Argo CD instance on the hub/tools cluster manages all spoke clusters.
ACM enforces the openshift-gitops operator on managed clusters via policy.
The cluster list in the ApplicationSet has one entry per managed cluster.

This model corresponds to the architecture in the original PDF diagrams.

```mermaid
%%{init: {'flowchart': {'curve': 'step', 'padding': 20}}}%%
flowchart LR
    classDef git      fill:#e3f2fd,stroke:#1565c0,color:#000
    classDef argo     fill:#fff8e1,stroke:#e65100,color:#000
    classDef platform fill:#eceff1,stroke:#546e7a,color:#000
    classDef appteam  fill:#e8f5e9,stroke:#2e7d32,color:#000
    classDef hub      fill:#ede7f6,stroke:#4527a0,color:#000
    classDef policy   fill:#fce4ec,stroke:#c62828,color:#000

    GIT[("openshift-gitops\ngit repo")]:::git

    subgraph MGMT["«hub cluster» mgmt"]
        ACM["«ACM»"]:::hub
        POLICY["«policy»\nopenshift-gitops\n\nmanaged cluster label:\nopenshift-gitops=true"]:::policy
    end

    subgraph TOOLS["«tools cluster» tools"]
        OP_T["«operator»\nopenshift-gitops"]:::argo
        subgraph ARGOCD_T["«kind: ArgoCD» platform"]
            APPSET_P["«argo-appset»\nplatform app-of-apps"]:::argo
            APPSET_B["«argo-appset»\nbusiness app-of-apps"]:::argo
            APPS_P["«argo-app»\nconfig(n)…"]:::platform
            APPS_B["«argo-app»\nbusiness_app(n)"]:::appteam
        end
    end

    subgraph KAFKA["«cluster» kafka"]
        K8S_P1["«k8s objects»\nconfig(n)"]:::platform
        K8S_RBAC["«k8s objects»\nRBAC, ldapsync…"]:::platform
        K8S_A1["«k8s objects»\napp-n"]:::appteam
    end

    subgraph APP_N["«cluster» app-n"]
        K8S_P2["«k8s objects»\nconfig(n)"]:::platform
        K8S_A2["«k8s objects»\napp-n"]:::appteam
    end

    ACM    -->|"policy-enforcement\nbased on cluster labels"| TOOLS
    ACM    -->|"policy-enforcement\nbased on cluster labels"| KAFKA
    GIT    -->|"clusters/kafka/*.yaml\nclusters/app-n/*.yaml"| APPSET_P
    GIT    -->|"clusters/kafka/*.yaml\nclusters/app-n/*.yaml"| APPSET_B
    APPSET_P -->|"deploys\nbased on platform\ncluster labels"| APPS_P
    APPSET_B -->|"deploys\nbased on app\ncluster label"| APPS_B
    APPS_P -->|reconciles| K8S_P1
    APPS_P -->|reconciles| K8S_P2
    APPS_B -->|reconciles| K8S_RBAC
    APPS_B -->|reconciles| K8S_A1
    APPS_B -->|reconciles| K8S_A2
```

### Ownership breakdown (hub model)

```mermaid
%%{init: {'flowchart': {'curve': 'step', 'padding': 20}}}%%
flowchart TD
    classDef platform fill:#eceff1,stroke:#546e7a,color:#000
    classDef appteam  fill:#e8f5e9,stroke:#2e7d32,color:#000

    subgraph OWN["Configuration ownership"]
        direction LR
        P_GENERIC["platform-owned\nnot app-specific\n\nrbac, oauth, splunk,\nF5 CIS, etc."]:::platform
        P_SPECIFIC["platform-owned\napp-specific\n\napp-n argocd\napp-n RBAC\nldapsync, etc."]:::platform
        A_OWN["app-team-owned\n\napp-n configs\nkafka topics\ndatasync jobs…"]:::appteam
    end

    P_GENERIC  -->|"deployed by\nplatform app-of-apps"| DEST["destination clusters"]
    P_SPECIFIC -->|"deployed by\nbusiness app-of-apps"| DEST
    A_OWN      -->|"deployed by\nteam's own Argo CD\n(app-team dashboard)"| DEST
```

---

## Migration path: per-cluster → hub

The git repo requires **no structural changes**. The migration steps are:

1. Deploy hub Argo CD instance on the tools cluster.
2. Add managed cluster secrets to hub Argo CD (`clusters/<cluster>/app-of-apps/cluster-secret.yaml`).
3. Update the ApplicationSet `elements:` list to include all managed clusters.
4. Remove per-cluster Argo CD instances (optional, can coexist during transition).

Application names change from `k8s-sno---platform---app` to
`k8s-sno---platform---app` — identical, because the naming convention always
includes `clusterName` (ADR-0002, ADR-0004).
