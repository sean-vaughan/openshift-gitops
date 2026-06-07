---
marp: true
theme: default
style: |
  @import url('./marp-theme.css');
paginate: true
footer: "OpenShift GitOps — Agent Flywheel"
---

<!-- _class: title -->

# The Agent Flywheel

**Autonomous GitOps — AI-driven cluster operations**

Sean Vaughan · Platform Architecture
`github.com/sean-vaughan/openshift-gitops`

---

# Two flywheels, one system

The **infrastructure flywheel** reconciles clusters to Git.

The **agent flywheel** reconciles Git to *organizational intent*.

```
Organizational intent
        │
        ▼
  [Agent Flywheel]  ←── cluster events, drift, alerts
        │
        ▼  (pull requests)
  [Infrastructure Flywheel]
        │
        ▼
    Clusters
```

The agent doesn't deploy to clusters directly.
**It writes to Git. The infrastructure flywheel does the rest.**

---

# Why an agent flywheel?

Platform engineers spend their time on:

- Diagnosing why an operator is degraded
- Deciding which pre-upgrade steps apply to *this* cluster
- Writing gate file overrides for a new environment
- Chasing down OLM conflicts and stuck finalizers

These are **repetitive pattern-matching tasks** — exactly what LLMs are good at.

The goal: the engineer reviews and approves, the agent does the work.

---

# The stack

```
┌─────────────────────────────────────────────────┐
│              Agent Flywheel                      │
│                                                  │
│  Argo Events ──► Agent Service ──► GitHub PR     │
│      │              │                            │
│  (cluster        (LangGraph                      │
│   events)         + vLLM)                        │
│                     │                            │
│              openshift-toolbox                   │
│              (oc, helm, git)                     │
└─────────────────────────────────────────────────┘
         │                        │
         ▼                        ▼
   RHOAI / KServe          openshift-gitops
   (model serving)          (this repo)
```

---

# The model: local, on your hardware

**Red Hat OpenShift AI (RHOAI)** hosts the model on the GPU worker node.

```
mkl-mgmt-dev-1 cluster
├── control plane: Dell R820
│   └── RHOAI operator, pipelines, model registry
└── worker: GPU box (RTX 3090, 24 GB VRAM)
    └── vLLM serving Granite 3.3 8B
        └── OpenAI-compatible endpoint (in-cluster)
```

No external API dependency. No data leaves your infrastructure.
The same endpoint serves the agent, workbenches, and pipelines.

---

# Granite 3.3: the RHOAI-native choice

**IBM Granite 3.3 8B** — Red Hat's supported model for enterprise AI:

- Fits comfortably in 24 GB VRAM (fp16: ~16 GB)
- Strong on structured output (YAML, JSON)
- Strong on code (Kubernetes manifests, shell)
- Backed by Red Hat support contract via RHOAI
- Tool-use capable (function calling)

Alternative: Qwen2.5-Coder 14B in 4-bit for deeper code reasoning.
Both run on the 3090.

---

# What the agent knows

The agent has access to:

| Context | How |
|---------|-----|
| This repo (all gate files, sources, ADRs) | Git clone at startup |
| Live cluster state | `oc` via openshift-toolbox |
| Argo CD Application health/sync | ArgoCD API |
| Operator catalog (available versions) | OLM API |
| Cluster events and alerts | Argo Events / Prometheus |

It can *read* anything. It *writes* only to Git (pull requests).

---

# Example: OLM degraded → auto-PR

```
1. Argo Events detects: Application "lvm-storage" Degraded

2. Agent reads:
   - Application status (ResolutionFailed on Subscription)
   - Live Subscription object (startingCSV conflict)
   - sources/lvm-storage/subscription.yaml
   - ADR-0003 (startingCSV policy)

3. Agent diagnoses: orphaned CSV, same pattern as prior incidents

4. Agent writes PR:
   Title: "fix: resolve OLM startingCSV conflict in lvm-storage"
   Body:  diagnosis + remediation steps + references to ADR-0003
   Change: (none needed — source already correct, proposes imperative fix)

5. Engineer reviews, approves → agent executes fix via toolbox
```

---

# Example: cluster upgrade

```
1. Trigger: engineer opens PR setting desiredUpdate.version in gate file

2. Agent reads:
   - OCP release notes for target version
   - Installed operators and their compatibility matrix
   - Known pre-upgrade steps for this cluster profile

3. Agent comments on PR:
   - Breaking changes relevant to installed operators
   - Required pre-upgrade steps
   - Estimated upgrade window

4. Engineer approves → infrastructure flywheel applies ClusterVersion
5. Agent monitors upgrade, detects issues, proposes fixes
6. Agent opens post-upgrade validation PR
```

---

# The structured repo enables the agent

The repo's strict structure is what makes the agent tractable.

```
clusters/<cluster>/<app>.yaml  ← the agent's action space
sources/<app>/                 ← what it can read and understand
docs/adr/                      ← the rules it reasons against
```

An agent operating against snowflake configs fails unpredictably.
An agent operating against this structure can be **tested and trusted**.

**The infrastructure flywheel wasn't just for humans.**

---

# Argo Events: the trigger layer

```yaml
# EventSource: watch for Application health changes
apiVersion: argoproj.io/v1alpha1
kind: EventSource
spec:
  argoWorkflows:
    app-health-change:
      namespace: openshift-gitops
      healthStatus: Degraded
```

Degraded → trigger → agent workflow → diagnosis → PR or action.

Other triggers: alert firing, new cluster registered, operator update available,
drift detected, scheduled review.

---

# Data Science Pipelines: the workflow layer

Agent workflows run as **Kubeflow Pipeline runs** on RHOAI:

```
[EventSource trigger]
        │
        ▼
[Pipeline: diagnose-and-remediate]
  ├── gather-context (oc, git)
  ├── invoke-model (vLLM endpoint)
  ├── validate-output (schema check)
  ├── create-pr (GitHub API)
  └── notify (Slack / email)
```

Each step is a container. Full audit trail. Re-runnable.
Failed runs are inspectable in the RHOAI dashboard.

---

# Roadmap

| Phase | What |
|-------|------|
| **Now** | RHOAI + GPU operator sources defined in git |
| **Phase 1** | GPU worker registered, RHOAI DataScienceCluster active, vLLM serving Granite |
| **Phase 2** | openshift-toolbox as agent execution environment |
| **Phase 3** | Argo Events triggers, first agent workflow (OLM diagnosis) |
| **Phase 4** | Upgrade automation agent |
| **Phase 5** | Autonomous steady-state operations |

---

# Summary

The agent flywheel is:

- **An inner loop** — writes to Git, never to clusters directly
- **Local-first** — model runs on your GPU, data stays in your infrastructure
- **Structure-dependent** — the repo's schema is what makes it safe
- **Incremental** — each phase adds autonomy without removing human review
- **Extensible** — new triggers, new workflows, same foundations

> "The infrastructure flywheel wasn't just for humans."

---

<!-- _class: title -->

# Questions?

`github.com/sean-vaughan/openshift-gitops`

Sources: `sources/rhoai/`, `sources/nvidia-gpu-operator/`
ADRs: `docs/adr/`
