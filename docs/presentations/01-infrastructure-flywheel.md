---
marp: true
theme: default
style: |
  @import url('./marp-theme.css');
paginate: true
footer: "OpenShift GitOps — Infrastructure Flywheel"
---

<!-- _class: title -->

# The Infrastructure Flywheel

**OpenShift GitOps — How it works and why it matters**

Sean Vaughan · Platform Architecture
`github.com/sean-vaughan/openshift-gitops`

---

# What is a flywheel?

A flywheel is a **self-reinforcing loop** — the more it spins, the more it resists stopping.

In GitOps:
- Git is the **single source of truth**
- Argo CD continuously **reconciles** cluster state to match Git
- Any drift is **automatically corrected**
- Changes flow in **one direction**: Git → Cluster

The flywheel never stops. You don't push deployments — you **declare intent**.

---

# The loop

```
┌─────────┐    PR + merge    ┌─────────┐
│  Human  │ ───────────────► │   Git   │
│  intent │                  │  (main) │
└─────────┘                  └────┬────┘
                                  │  Argo CD polls
                                  ▼
                           ┌─────────────┐
                           │   Argo CD   │  detects drift
                           │ApplicationSet│ ◄──────────────┐
                           └──────┬──────┘                 │
                                  │ applies                 │
                                  ▼                         │
                           ┌─────────────┐                 │
                           │   Cluster   │ ────────────────►┘
                           │   (k8s)     │  live state
                           └─────────────┘
```

---

# Repo structure

```
openshift-gitops/
├── clusters/          # Gate files — what runs where
│   └── k8s-sno/
│       ├── lvm-storage.yaml        ← {} = org defaults
│       └── openshift-gitops.yaml   ← overrides only
│
├── sources/           # What to deploy — one dir per app
│   ├── lvm-storage/
│   └── openshift-gitops/
│
└── profiles/          # Who owns what
    └── teams/platform/app-project.yaml
```

**The presence of a gate file deploys an app to a cluster.**
An empty file (`{}`) uses all org defaults.

---

# App-of-apps: the ApplicationSet

One `ApplicationSet` generates all `Application` objects from a matrix:

```
clusters × gate files = Applications
```

```yaml
generators:
  - matrix:
      generators:
        - list:
            elements:
              - clusterName: k8s-sno      # ← each cluster
        - git:
            files:
              - path: 'clusters/{{ .clusterName }}/*.yaml'  # ← gate files
```

Adding a cluster = adding an element.
Adding an app to a cluster = adding a gate file.

---

# Configuration cascade (ADR-0003)

Defaults flow down. Overrides live only where they're intentional.

```
ApplicationSet template (org defaults)
    │
    └─► clusters/<cluster>/<app>.yaml   (cluster overrides via templatePatch)
            │
            └─► sources/<app>/          (base manifests)
                    │
                    └─► clusters/<cluster>/<app>/   (kustomize overlay, if needed)
```

**Gate files contain only intentional deviations.** Empty `{}` means "I accept all defaults."

---

# Application naming (ADR-0002)

```
<clusterName>---<projectName>---<appName>
```

Example: `k8s-sno---platform---lvm-storage`

- `clusterName` — Argo CD cluster secret name
- `projectName` — AppProject (authorization boundary)
- `appName` — gate file filename without `.yaml`

Derivable from structure. No configuration needed.

---

# Cluster naming (ADR-0007)

```
<dc>-<type>-<env>-<n>
```

| Segment | Example | Meaning |
|---------|---------|---------|
| `dc` | `mkl` | Mukilteo data center |
| `type` | `mgmt` | Management cluster type |
| `env` | `dev` | Development environment |
| `n` | `1` | Sequence number |

Result: `mkl-mgmt-dev-1`

No snowflakes. Every cluster name encodes its role, location, and environment.

---

# AppProjects and teams (RBAC)

Every app belongs to an **AppProject**.
Every AppProject is owned by one or more **teams** (from LDAP groups).

```yaml
# profiles/teams/platform/app-project.yaml
teams:
  - name: platform-admins
    role: admin
  - name: platform-devs
    role: edit
```

Generates → Argo CD `AppProject` with matching `roles`.
Reflects → OpenShift `admin`/`edit`/`view` RBAC on target namespaces.

One Helm chart (`sources/app-projects`) renders all AppProjects from values.

---

# What we run today (k8s-sno)

| Application | Purpose |
|-------------|---------|
| `sealed-secrets` | Encrypted secrets safe for git |
| `lvm-storage` | Local volume management (LVM-based PVs) |
| `openshift-gitops` | Self-managing: Argo CD manages itself |
| `app-projects` | AppProject RBAC for all teams |
| `app-of-apps` | The ApplicationSet — the flywheel engine |
| `host-inventory` | Bare-metal host catalog (RHACM/AI) |
| `openshift-virtualization` | KubeVirt — VMs on OpenShift |
| `rhacm` | Hub cluster: multi-cluster management |

8 applications. 1 ApplicationSet. 0 manual deployments in steady state.

---

# Bootstrap: the one-time seam (ADR-0005)

The flywheel can't start itself. One manual step:

```bash
# 1. Install GitOps operator
oc apply -f sources/openshift-gitops/

# 2. Bootstrap AppProject (ApplicationSet can't create apps without it)
helm template sources/app-projects --values sources/app-projects/platform.yaml \
  | oc apply -f -

# 3. Seed the flywheel
oc apply -f clusters/<cluster>/app-of-apps/cluster.yaml
oc apply -f bootstrap-application.yaml

# After this: the flywheel runs forever.
```

Everything after this single bootstrap is GitOps-driven.

---

# Development workflow (ADR-0006)

```
feature/my-change  ──► PR ──► main ──► cluster auto-syncs
```

For cluster validation:
1. Create feature branch
2. Gate file pins `targetRevision: feature/my-change`
3. Validate on dev cluster
4. Remove pin, open PR to `main`
5. Cluster auto-syncs from `main` after merge

Changes to `sources/` are always validated on a dev cluster first.
`main` is always production-ready.

---

# Summary

The infrastructure flywheel gives you:

- **Single source of truth** — Git is the cluster
- **Self-healing** — drift is corrected automatically
- **Auditable** — every change is a PR with history
- **Scalable** — adding a cluster is adding a directory
- **Safe by default** — production requires a PR

> "You don't push deployments — you declare intent."

---

<!-- _class: title -->

# Questions?

`github.com/sean-vaughan/openshift-gitops`

ADRs: `docs/adr/`
Diagrams: `docs/diagrams/`
