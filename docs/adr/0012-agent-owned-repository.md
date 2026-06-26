# ADR-0012: OpenShift Genesis — agent-owned repository and flywheel governance

- **Status**: Proposed
- **Date**: 2026-06-16

## Context

The flywheel today is human-authored: people write manifests into `sources/`,
gate files into `clusters/`, and profiles into `profiles/`; the app-of-apps
ApplicationSet derives Argo CD Applications from that structure; Argo CD
reconciles desired state onto clusters. The `gitops-agent` execution environment
(distinct from the human `openshift-toolbox` shell) exists to automate this
flywheel, but it is still a tool a human picks up and drives.

This ADR names that automation **OpenShift Genesis** — the agent that can create
and own the repository, named for its defining act: producing the flywheel from a
bare cluster. "OpenShift Genesis" is the agent/product; `gitops-agent` remains the
execution-environment image it runs in, preserving the two-image split.

The roadmap's later phases call for an **agentic flywheel**: a world in which the
agent owns the repository and manages it on an ongoing basis — authoring config,
keeping documentation in sync, capturing cluster drift (ADR-0011), and proposing
changes continuously — with a human acting only as a final approval gate where it
matters. This ADR defines how the agent can own the repo **without** weakening
the trust model the repo depends on.

The central design tension: maximize how much the agent can do unattended, while
ensuring git remains the auditable source of truth and a human stays in the loop
for anything consequential. An agent that writes directly to clusters, or that
auto-merges freely, would dissolve the guarantees of ADR-0005 (flywheel
self-reference) and ADR-0008 (branch protection).

### Constraints

1. **Git stays authoritative; the agent only ever writes git, never clusters.**
   The agent is a contributor, not a controller. It proposes changes to the repo;
   Argo CD remains the only thing that moves state onto clusters. This preserves
   the existing reconciliation guarantees unchanged.
2. **Every change is a branch + PR.** The agent never pushes to `main`. This is
   the same gate every human contributor passes (ADR-0008), so the agent cannot
   bypass review by construction — only the autonomy policy decides whether a
   *human* must approve, never whether review happens at all.
3. **CI gates everything (ADR-0009).** Schema validation and ADR-compliance
   linting run on agent PRs identically to human PRs. The agent earns no
   exemption.
4. **Documentation is a required output, not a courtesy.** A config change that
   does not also update the affected docs / knowledge records is incomplete. The
   agent must record *why*, not just *what*.
5. **The agent's own autonomy is the highest-trust surface.** Any change to the
   autonomy policy, the agent's deployment, or its credentials always takes the
   strictest gate (human approval), regardless of any other rule.
6. **Conservative by default.** Unclassifiable or unrecognized changes fail safe
   to the human-approval lane. The cost of an unnecessary human review is far
   lower than the cost of an erroneous auto-merge.
7. **Supportability is a first-class output.** Config that would fall outside Red
   Hat's supported configuration is a defect, not a stylistic preference. The
   agent must recognize and surface it, never propose it silently.
8. **Security findings drive change; they do not bypass review.** Vulnerability
   and policy signal (RHACS) is just another sensor — it raises the priority of a
   change, but security-touching changes still take the strictest gate.

## Decision

The agent becomes the repository's primary author under a **conservative
auto-merge** governance model, with a machine-readable knowledge layer (Open
Knowledge Format) carried alongside human-readable ADRs.

### The authoring loop

```
 sensors ──► agent authors ──► branch + PR ──► CI (ADR-0009)
   │            change           │                  │
   │                             │                  ▼
   │                             │           classify PR lane
   │                             │            │            │
   │                             │      auto-merge      human-approval
   │                             │       (narrow)        (default)
   │                             ▼            │            │
   └──────────────── Argo CD reconciles merged main ◄──────┘
```

**Sensors** are the inputs that tell the agent the repo should change. The
config-harvester (ADR-0011) is one sensor (cluster drift → proposed capture).
Others: new operator channel availability, cluster health signals, an issue or
ticket. Many sensors, one authoring path.

**Conversation is the primary, recommended sensor and UI.** A human chatting with
the agent — the agent surfacing findings (a drift capture, a proposed upgrade),
the human deciding, and the agent then committing and opening a PR — is a
first-class, recommended workflow for cluster development, not a fallback. This
session is itself an example: discuss, decide, the agent authors the branch and
PR, the governance gate applies. This satisfies the Red Hat AI requirement for a
chat interface to the platform. Conversational changes flow through the identical
authoring loop and governance lanes as any other sensor — chat lowers the
authoring threshold, it does not bypass review or auto-merge classification.

### Governance: conservative auto-merge

> **Amended by ADR-0017:** the load-bearing axis of these lanes is
> reversibility / blast-radius; the changed-path globs and kind checks below are
> *proxies* for it. Security-sensitive content stays `human-approval` regardless.
> This is a clarification of the lanes, not a widening of auto-merge.

Every PR is classified into exactly one lane. Classification is by changed-path
globs plus content checks; **anything unmatched falls to `human-approval`**.

**`auto-merge` lane** — the agent merges its own PR once CI is green. Restricted
to changes that are low-blast-radius and mechanically verifiable:

- Documentation and OKF knowledge records (`docs/**` except `docs/adr/**`,
  and `**/index.md` OKF docs).
- Dev/lab cluster gate files and `sources/` changes that resolve to non-prod
  clusters only (per ADR-0007 cluster classification).
- Config-harvester captures targeting dev/lab clusters.

A PR qualifies for `auto-merge` only if **all** changed paths match the allowlist
**and** none touch a security-sensitive kind (see below) **and** CI is green.

**`human-approval` lane** — the default, and mandatory for:

- Any change resolving to a **production** cluster.
- **Security-sensitive** content: RBAC (`Role`/`RoleBinding`/`ClusterRole*`),
  `Secret`/SealedSecret material, AppProject `roles`, anything under
  `sources/sealed-secrets/` or `sources/app-projects/`.
- **Structural** changes: new top-level directories, `schema/` changes, the
  ApplicationSet template in `sources/app-of-apps/`.
- **ADRs** (`docs/adr/**`) — decisions remain a human act the agent may draft but
  not ratify.
- **The autonomy policy itself**, the agent's deployment, or its credentials
  (constraint 5).

The policy is a declarative file in the repo and is itself in the
`human-approval` lane. "Optionally require PR approval as the final gate" is
realized as: the gate always exists; the policy only decides which PRs may skip
the *human* step. Turning off auto-merge entirely is a one-line policy change —
and that change requires human approval, as it must.

### Agent review roles: supportability and security

Beyond authoring, the agent applies two standing **review roles** to every change
it proposes and every config it harvests (ADR-0011). Both are advisory gates: they
annotate the PR and can *force* a change down to the `human-approval` lane, but
neither can merge on its own. They are personas the one agent adopts, not separate
agents — the chat interface (above) can also be addressed in either voice
("is this supported?", "what does RHACS say about this?").

**Red Hat Support Agent role — supportability gate.** The agent evaluates proposed
and harvested configuration against Red Hat's supported-configuration boundaries
and flags anything that risks falling outside support. Typical triggers: hand-edited
operator-managed (`openshift-*`) resources, unsupported `MachineConfig` /
`KubeletConfig` / kubelet tuning, disabled or removed cluster operators, unsupported
CNI/CSI or version-skew combinations, and any field the product docs mark as
"unsupported" or "will be reverted."

- **On harvest:** a captured object touching a Red-Hat-managed surface is tagged
  `supportability: review` in the PR body rather than merged quietly. This is
  exactly where hand-applied console edits — the drift ADR-0011 exists to catch —
  are most likely to be unsupported, so the support role and the harvester reinforce
  each other.
- **On authoring:** the agent declines to *propose* a known-unsupported config; it
  instead records the supported alternative (or opens an issue) and explains why.
- **Knowledge:** supportability rules are maintained as OKF reference records so the
  ruleset is auditable and tunable by PR, like the harvester's heuristics.
- **Caveat:** "supported" is a moving, sometimes account-specific target. The role
  is a high-recall advisor that flags for human judgement, not an authority on
  Red Hat's support contract.

**Red Hat Security Operations role — security gate, RHACS-integrated.** The agent
integrates with **Red Hat Advanced Cluster Security (RHACS / StackRox)** in both
directions:

- **RHACS as a sensor (drives change):** image CVEs, deploy-time policy violations,
  misconfigurations, and compliance failures reported by RHACS become authoring
  inputs — the agent proposes remediation PRs (pin/bump a vulnerable image, tighten
  a `SecurityContext`, add a missing `NetworkPolicy`, narrow over-broad RBAC). This
  makes RHACS a peer to the config-harvester in the sensor framework.
- **RHACS as a reviewer (gates change):** before opening a PR the agent checks the
  proposed manifests against RHACS build/deploy policies (privileged containers,
  `hostNetwork`/`hostPath`, `runAsRoot`, missing limits, mutable `latest` tags) so
  violations surface at PR time, not at admission.
- **Lane:** anything this role touches is security-sensitive by definition and
  routes to `human-approval` (constraint 8) — including *intentional* policy
  exceptions, which must be acknowledged by a human, not auto-merged. (The
  `hostNetwork` samba workload on `k8s-sno` is a concrete example: a real,
  deliberate RHACS-policy violation that should be flagged and human-acknowledged,
  never silently accepted.)
- **Self-managed:** RHACS itself is delivered as a normal source
  (`sources/rhacs/` — Central + SecuredCluster) by the same app-of-apps, and its
  policy set is git-managed config like everything else, so the security baseline is
  in the flywheel rather than configured out of band.

### Knowledge layer: Open Knowledge Format

The agent maintains an **OKF bundle** describing the repo's assets and their
relationships, co-located with what it describes (consistent with this repo's
"derivability from structure" principle):

- Each `sources/<app>/` and `clusters/<cluster>/` carries an OKF `index.md`
  (markdown + YAML frontmatter: `type`, `title`, `description`, `resource`,
  `tags`, `timestamp`), cross-linked to related assets via markdown links.
- A top-level OKF `index.md` is the bundle root **and** the first-light manifest:
  its frontmatter records the organizational dimensions chosen by the first-light wizard
  (teams, data-centers, environments, cluster-types, hub vs single-cluster), and
  its body links out to the per-app and per-cluster OKF docs. The repo's shape and
  the repo's knowledge graph share one root.

OKF is adopted as a **format, not a platform**: no SDK, account, or runtime
dependency — just markdown+YAML in git, which every existing tool here already
reads. Google's reference enrichment-agent and HTML visualizer are explicitly
out of scope; they may be revisited as optional conveniences.

**Layer boundaries (to avoid a fourth overlapping doc system):**

- **OKF docs** describe *assets* — what each app/cluster/config domain is, how it
  relates to others, and provenance (which sensor/agent run authored it, when).
- **ADRs** remain the *human decision* record — rationale and trade-offs for
  structural choices.
- They cross-link. OKF augments ADRs; it never replaces them.

The agent consumes the OKF graph for context on each run rather than re-deriving
intent from raw YAML — this is the durable, portable form of the agentic
flywheel's memory. OKF v0.1 is early and will churn; because the payload is plain
markdown+YAML, tracking spec revisions is low-cost.

### Self-reference

The agent's deployment, its sensor configuration, and the autonomy policy all
live in the repo and are managed by the same flywheel (ADR-0005). The agent that
owns the repo is deployed *by* the repo. The bootstrapping invariant: changes to
the agent's own autonomy or identity always route to `human-approval`, so the
agent can never widen its own authority unattended.

### Alignment with Red Hat AI: BYOA and AgentOps

OpenShift Genesis is, in Red Hat's terms, a **Bring Your Own Agent (BYOA)** case:
a framework-specific agent that the platform operationalizes without modifying its
code. Red Hat's BYOA bar is *"the agent has identity, runs under least-privilege,
gets observed, passes safety checks, and can be audited."* Genesis is **designed to
clear that bar and to consume Red Hat AI's operational plane rather than re-invent
it** — Genesis owns *what config is correct, supported, and secure*; the platform
owns *how the agent is identified, sandboxed, observed, and policy-gated at runtime*.

Genesis's existing trust mechanisms map onto Red Hat primitives, and where a
primitive supersedes a hand-rolled equivalent, Genesis adopts it:

- **Identity** — the out-of-band credential footprint of first light is replaced, as
  soon as the platform is present, by **SPIFFE/SPIRE** short-lived scoped workload
  identity. This directly retires the "agent is a high-value target; scope its
  credentials" risk below, and shrinks the irreducible cold-start footprint.
  **Kagenti** (planned for Red Hat AI H2 2026) is the named product layer that
  operationalizes SPIFFE/SPIRE for agent lifecycle management and policy binding in
  the Red Hat ecosystem. Genesis plans to adopt Kagenti as its lifecycle integration
  point when it reaches preview, rather than carrying bespoke SPIFFE wiring — the
  protocol (SPIFFE) is a design invariant; Kagenti is the preferred product
  realization of it.
- **Least-privilege & isolation** — the PR-only git token and read-only ClusterRole
  (ADR-0011) are complemented by **sandboxed-container, per-session** execution of
  the `gitops-agent` image.
- **Runtime tool-use policy** — **OPA/Gatekeeper, Kyverno, and the MCP Gateway**
  gate the agent's *own* tool/MCP calls at runtime. This is a distinct layer from
  Genesis's support and security review roles, which gate the *config the agent
  writes* at PR time. The two layers stack; neither replaces the other.
- **Safety** — input/output screening (TrustyAI Guardrails, NeMo, Garak) wraps the
  agent without touching its logic, consistent with constraint 5 (the agent cannot
  widen its own authority).
- **Observability (AgentOps)** — Genesis already emits a human-readable *why* (the
  "documentation is a required output" constraint) and git-native provenance (OKF
  records of which sensor/run authored a change). **AgentOps** — reasoning-loop
  traces via MLflow/OpenTelemetry, supervisory evaluation — is the machine-telemetry
  complement: the OKF provenance record is a lightweight git-native slice of the
  fuller AgentOps trace. Genesis exports to the AgentOps plane rather than carrying
  its own tracing backend.
- **Human-in-the-loop** — Genesis's governance lanes (auto-merge vs
  `human-approval`) *are* the AgentOps human-checkpoint concept, realized at the PR
  boundary.

**Cost/budget tracking** — AgentOps treats per-run resource/token cost as a
first-class signal; Genesis had no notion of it. This is now addressed by
**ADR-0013** (agent self-metering, a declarative budget policy, budget-aware
prioritization, and human-gated budget requests), the budget policy being a sibling
of the autonomy policy above.

This alignment is a **posture, not a hard dependency**: first light must still
cold-start on a lightly-configured cluster before any of this plane exists (see
below), so Genesis degrades to its git-native guarantees when the platform is
absent and adopts the platform primitives as they come online.

### First light: bootstrapping from scratch

Simplicity of cold-start is a hard requirement: **OpenShift Genesis** must be able
to begin with **no repository and only a lightly-configured cluster** — ready, go.
This cold-start moment is *first light*: dark cluster, agent runs, the repo comes
into being. The first-light sequence runs entirely from the agent, producing the
repo as its first act:

1. **Scaffold** — create the strict directory skeleton (`sources/`, `clusters/`,
   `profiles/`, `docs/`, `schema/`), a baseline `CLAUDE.md`, `README.md`, and the
   foundational ADRs the repo's conventions depend on. The scope of the scaffold
   is set by the **first-light wizard** (below) — only the organizational dimensions
   the user opts into are materialized.
2. **Harvest** — run the config-harvester (ADR-0011) against the lightly-
   configured cluster to populate `sources/<app-name>/` from what already exists,
   using the placement rules in ADR-0011 (Project name → app name).
3. **First PR** — open the first-light change as a single reviewable PR (or an
   initial commit a human ratifies) rather than auto-merging — a from-scratch
   first light is,
   by definition, unclassifiable and therefore takes the `human-approval` lane.

### First-light wizard

The repo's ethos is derivability over explicit configuration — but an
organization's *shape* (whether it has teams, multiple data centers, a dev→prod
ladder) is not derivable from a bare cluster; it is a human fact. The first-light
wizard is the single, deliberate concession to up-front configuration: one
guided questionnaire that decides which optional organizational dimensions the
repo will model. Each "yes" materializes the corresponding structure; each "no"
leaves it out, keeping a lab cluster's repo minimal.

Indicative questions, each mapping to a repo concept:

- **Cluster-type profiles?** — canonical app sets per class of cluster, composed
  from app-groups (`profiles/`). No → clusters reference apps directly.
- **App-groups?** — reusable app collections cluster-types pull in. No → flat
  per-cluster-type app lists.
- **Team profiles?** — LDAP-group-derived teams mapped to AppProject roles. No →
  a single default AppProject/owner.
- **Data-center profiles?** — DC-specific overrides and the
  `<dc>-<type>-<env>-<n>` naming convention (ADR-0007). No → free-form cluster
  names (lab mode, e.g. `k8s-sno`).
- **Environment promotion?** — a dev/staging/prod ladder (ADR-0006). No →
  single-environment.
- **Hub / multi-cluster (RHACM)?** — vs a single self-managed cluster.

Two properties keep the wizard honest:

- **The harvest pre-fills it.** The config-harvester (ADR-0011) runs first as a
  sensor; what it observes sets the defaults. One free-form-named cluster defaults
  the wizard to lab mode and asks for confirmation rather than interrogating from
  zero — answers, not an interview.
- **Answers persist as committed config**, not a one-shot prompt. The wizard
  writes its answers into the **top-level OKF `index.md`** (the bundle root,
  see "Knowledge layer" above), which both bounds the scaffold and drives
  ongoing agent behavior (e.g. *team profiles: yes* tells the harvester to map
  captured RBAC into team structures; *no* leaves it as plain RoleBindings in the
  app source). Enabling a dimension later is a config change plus a scaffolding
  PR, on the `human-approval` lane.

The wizard runs as **pure chat** (satisfying the chat-interface requirement and
the cold-start case where no console plugin is yet deployed) and, once available,
as a **console-plugin form** — the same answers, two surfaces.

The chicken-and-egg constraint: before the repo exists, the agent's own
deployment cannot yet be repo-managed. First light therefore tolerates a minimal,
documented out-of-band starting footprint (agent credentials + cluster access),
and its **first** authored content includes the agent's own deployment manifests
— so that immediately after first light, the agent is self-referentially managed
(ADR-0005) and no longer depends on the out-of-band footprint. Keeping that
initial footprint as small as possible is the design priority; everything beyond
the irreducible minimum must come from the harvest, not from hand-configuration.

## Consequences

**Positive:**

- Realizes the roadmap's agentic-flywheel phase without weakening the trust
  model: git stays authoritative, every change is a reviewed PR, CI is universal,
  and a human gates everything consequential.
- The trust model is *configurable, not bolted-on* — autonomy is a declarative,
  versioned, auditable policy, and dialing it down to "human approves everything"
  is a one-line, human-approved change.
- Documentation and provenance stop drifting: they are required outputs of the
  same loop that makes the change, captured both human-readably (ADRs) and
  machine-readably (OKF).
- OKF gives the agent durable, portable, vendor-neutral memory that doubles as
  human-browsable docs — at the cost of plain markdown files.
- The config-harvester (ADR-0011) becomes one sensor in a general framework
  rather than a bespoke workload.
- Supportability and security stop being after-the-fact audits and become
  properties checked *as the change is authored*: unsupported config is flagged at
  harvest/PR time, and RHACS findings drive remediation PRs through the same loop —
  with the RHACS baseline itself living in the flywheel.
- Positioning Genesis as a BYOA-compliant agent lets it consume Red Hat AI's
  operational plane (SPIFFE/SPIRE identity, sandboxed execution, OPA/Kyverno/MCP
  policy, AgentOps tracing) instead of re-inventing it — notably retiring the
  out-of-band credential footprint and the "high-value target" risk via workload
  identity, and slotting Genesis into Red Hat's ecosystem rather than competing with
  it.
- The strict structure becomes *progressive*: the first-light wizard scaffolds only
  the organizational dimensions a user opts into, so a single-node lab and a
  multi-DC enterprise share one repo grammar without the lab paying for empty
  boilerplate. Growing into a new dimension later is a normal, reviewed change.

**Negative / constraints:**

- **The approval gate is only as strong as reviewer attention.** A high volume of
  agent PRs invites rubber-stamping, which would make the human lane theater.
  Mitigations — a deliberately narrow auto-merge allowlist, PR batching, and
  rate limits — are essential, not optional, and must be tuned in practice. Phase
  0 of ADR-0011 already showed one sensor producing dozens of candidates per run.
- An agent with repo-write, cluster-read, and any auto-merge authority is a
  high-value target. Credentials must be scoped (PR-only where possible), commits
  signed, and the autonomy policy treated as a hard security boundary.
- Conservative classification will route many safe-but-unrecognized changes to
  humans, adding review load until the allowlist matures. This is the intended
  failure direction.
- OKF v0.1 is immature; the schema may change under us. Co-locating OKF docs also
  adds an `index.md` maintenance surface to every app/cluster directory.
- The supportability ruleset is a maintenance burden and can never be exhaustive or
  authoritative; it will both miss unsupported config and occasionally over-flag
  supported config. It is an advisor, and a wrong "supported" verdict could lend
  false confidence — hence high-recall, human-judged, never a merge gate on its own.
- RHACS integration adds an external dependency and a sizable workload (Central +
  SecuredCluster) to the estate, and turns RHACS policy into yet another tunable
  surface; a noisy or misconfigured policy set would generate remediation-PR churn.
- Consuming Red Hat AI's plane couples Genesis to a substantial set of platform
  components (SPIFFE/SPIRE, OPA/Gatekeeper, Kyverno, MCP Gateway, TrustyAI,
  MLflow/AgentOps). The posture deliberately keeps these optional so first light
  still cold-starts without them, but the "fully aligned" end state is a large
  integration surface to track as those Red Hat offerings themselves mature.
- Cost/budget tracking of agent runs is addressed separately in ADR-0013; until that
  lands, Genesis cannot bound or report the resource/token cost of its own activity.
- This is a large new capability surface (sensors, classifier, OKF maintenance,
  auto-merge automation) to build and operate. It should be staged, not landed at
  once — config-harvester as the first sensor, manual PRs before any auto-merge,
  auto-merge enabled last and narrowly.

## Related

- ADR-0005: Flywheel self-reference
- ADR-0008: Branch protection and repository governance
- ADR-0009: CI linting and ADR compliance
- ADR-0011: Cluster config harvesting (the first sensor)
- ADR-0001: Sources organized by application (asset structure OKF mirrors)
- [Open Knowledge Format (Google Cloud)](https://cloud.google.com/blog/products/data-analytics/how-the-open-knowledge-format-can-improve-data-sharing)
- `GoogleCloudPlatform/knowledge-catalog` (OKF spec + samples)
- Red Hat Advanced Cluster Security for Kubernetes (RHACS / StackRox) — security
  sensor + deploy/build policy gate, delivered as `sources/rhacs/`
- Red Hat supported-configuration / supportability boundaries (support role ruleset)
- [Operationalizing Bring Your Own Agent — Red Hat AI (OpenClaw edition)](https://www.redhat.com/en/blog/operationalizing-bring-your-own-agent-red-hat-ai-openclaw-edition)
- [AgentOps (Red Hat)](https://www.redhat.com/en/topics/ai/agentops)
- [OpenClaw](https://openclaw.ai) — the BYOA reference agent in Red Hat's example
- ADR-0013: Agent cost metering and budget governance (the cost dimension of AgentOps)
- ADR-0015: Multi-cluster topology — hub-push vs. Argo CD Agent pull-based (the
  multi-cluster deployment model for Genesis; Argo CD Agent went GA in OpenShift
  GitOps 1.19, January 2026, making pull-based topology a production-grade
  alternative for disconnected or firewall-constrained spoke clusters)
- ADR-0016: Sensor-driven remediation PR authoring (Genesis's own remediation-PR
  loop, extending the authoring loop defined here to multi-sensor remediation)
- [Wiring Zero Trust Identity for AI Agents — Kagenti, SPIFFE, Token Exchange (Red Hat Emerging Tech, 2026-06-10)](https://next.redhat.com/2026/06/10/wiring-zero-trust-identity-for-ai-agents-spiffe-token-exchange-and-kagenti/)
- [Argo CD Agent GA — OpenShift GitOps 1.19 (Red Hat Developer, 2026-01-12)](https://developers.redhat.com/blog/2026/01/12/whats-new-openshift-gitops-119)
- ADR-0017: Loop engineering and the autonomous-decision review role (frames this
  authoring loop as the four-loop stack; adds the Verifier/Auditor review role; refines
  the governance classifier onto the reversibility/blast-radius axis)
