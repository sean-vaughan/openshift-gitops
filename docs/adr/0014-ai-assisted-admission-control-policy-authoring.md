# ADR-0014: AI-assisted OPA Gatekeeper admission control policy authoring

- **Status**: Proposed
- **Date**: 2026-06-18

## Context

ADR-0012 defines two standing review roles for OpenShift Genesis: a supportability
gate and a security gate integrated with RHACS. Both roles are **reactive** — they
evaluate configuration *after* it is proposed or *after* it is running. Neither
addresses the earlier, preventive layer: **admission control** policies that reject
or warn on non-compliant workloads at deploy time, before they land on the cluster.

OPA Gatekeeper fills that preventive layer. A `ConstraintTemplate` defines a Rego
rule; a `Constraint` instance applies it with cluster-specific parameters. Together
they express organizational security and compliance intent as enforceable admission
webhooks. Red Hat's OpenShift hardening guidance covers a well-understood set:
privilege escalation, `hostNetwork`/`hostPath`, `runAsRoot`, missing resource
limits, mutable `latest` image tags, missing `NetworkPolicy`, over-broad RBAC, and
others. These are the same findings RHACS surfaces at runtime — but a Gatekeeper
policy blocks them at the gate rather than alerting after the fact.

The practical gap is **policy authoring**. Writing correct Rego is a specialist
skill. Platform teams are therefore either under-invested in Gatekeeper (accepting
reactive-only enforcement) or spending a disproportionate share of platform-team
time on policy authoring and maintenance — the "Rego tax" described by Red Hat's
emerging-technologies team. Neither outcome is acceptable for a flywheel whose
ambition is comprehensive, continuously maintained compliance posture.

AI-assisted policy authoring addresses this, with an important constraint: **LLMs
can generate plausible-looking but logically incorrect Rego**. A subtle policy bug
— wrong operator, inverted condition, incomplete `input.review` path — produces
silent over-permissiveness rather than an error. In security policy this is the
worst failure mode: the policy passes CI, the constraint deploys, and non-compliant
workloads slip through with no signal. Therefore the agent must never generate Rego
from scratch. It selects and parameterizes from a curated, peer-reviewed template
library. LLM reasoning applies to *which template* and *what parameters* — not to
Rego authorship.

A second constraint follows from ADR-0012's governance model: Gatekeeper policies
are security-sensitive configuration. Every new policy and every enforcement
promotion routes through the `human-approval` lane. The agent proposes; a human
ratifies. The dryrun-first promotion cadence makes the human checkpoint meaningful:
a reviewer can inspect actual violation counts before approving enforcement.

### Relationship to ADR-0012

ADR-0012 names OPA/Gatekeeper and Kyverno as a **runtime tool-use policy layer**
that gates the agent's own MCP calls at runtime — a safety wrapper *around* Genesis.
This ADR is orthogonal: it defines Genesis as a **policy author** that produces
Gatekeeper `ConstraintTemplate` and `Constraint` resources as repo deliverables,
deployed to clusters via the same app-of-apps flywheel as every other source.

ADR-0012's RHACS integration and this ADR's Gatekeeper authoring are complementary
sensors in the same authoring loop:

- **RHACS** → runtime violations, CVEs, deploy-time policy failures → remediation PRs
- **Gatekeeper posture sensor** (this ADR) → gaps in preventive coverage → new
  policy PRs

Both feed the Genesis authoring loop. Neither replaces the other.

## Decision

OpenShift Genesis adopts OPA Gatekeeper admission control policy authoring as a
first-class sensor-and-output capability, governed by three principles:

1. **Template-library-first**: the agent never authors raw Rego. It selects and
   parameterizes from a versioned, curated template library.
2. **Dryrun-first promotion**: every new policy enters enforcement at `dryrun`,
   advancing to `warn` and then `deny` only after a human-approved monitoring window.
3. **Human-approval for all policy changes**: new templates, new constraints, and
   every enforcement promotion are security-sensitive changes and route to the
   `human-approval` lane, regardless of cluster classification.

### Template library

The template library lives in `schema/gatekeeper-templates/`. Each entry is a pair:

- A `ConstraintTemplate` YAML file — the Rego rule, human-authored and peer-reviewed.
- A companion parameter schema describing what values a `Constraint` instance must
  supply and what each controls.

Templates cover the Red Hat OpenShift hardening baseline (privilege escalation,
`hostNetwork`/`hostPath`, `runAsRoot`, resource limits, image mutability, missing
`NetworkPolicy`, RBAC scope) plus organization-specific additions that may accrue
over time. The library is versioned in git; adding or modifying a template is a
`human-approval` PR. Genesis may *propose* new templates by opening a PR; it never
auto-merges them.

The library is small and stable by design. The agent's intelligence is applied to
**selection and parameterization**, not to expanding the library. A finding that
no template covers is flagged for human authorship, not improvised — the agent
opens an issue rather than generating novel Rego.

### Authoring loop

```
posture sensor ──► analyze cluster ──► identify gaps ──► select template
      │                │                     │                  │
  (schedule /        (MCP /               (coverage         (from schema/
  RHACS signal)    cluster API)            matrix)        gatekeeper-templates/)
                                                               │
                                                      parameterize Constraint
                                                               │
                                                      ┌────────▼────────┐
                                                      │  branch + PR    │
                                                      │  enforcementAction:│
                                                      │  dryrun         │
                                                      └────────┬────────┘
                                                               │
                                                        human-approval
                                                               │
                                                      merge → Argo CD deploys
                                                               │
                                                      monitoring window
                                                               │
                                              ┌────────────────▼──────────────────┐
                                              │  promotion PR                      │
                                              │  dryrun → warn  (then warn → deny) │
                                              └────────────────┬──────────────────┘
                                                               │
                                                        human-approval
```

**Posture sensor**: the trigger for a policy-authoring run. Two sources:

- **Scheduled analysis** — a periodic scan of cluster workloads against the
  template library's coverage matrix, identifying namespaces or workload classes
  not yet covered by a constraint.
- **RHACS signal** — a runtime violation type that RHACS is detecting repeatedly
  but no Gatekeeper constraint is blocking at admission. RHACS thus becomes a
  feedback loop: patterns that escape preventive coverage surface naturally as
  candidates for a new constraint.

**Analysis**: the agent queries the cluster via MCP/Kubernetes API to enumerate
live workloads, existing Gatekeeper constraints, and the violation types observed.
It builds a coverage matrix: which hardening categories have constraints, which
are absent or scoped too narrowly.

**Gap identification**: each gap is a candidate Constraint instance. Candidates are
ranked by violation frequency (RHACS signal), blast radius (cluster scope vs
namespace scope), and alignment with the org's current hardening posture.

**Template selection and parameterization**: the agent selects the appropriate
`ConstraintTemplate` from the library and fills in the Constraint parameters
(target namespaces, excluded namespaces, enforcement scope). Parameter choices and
their rationale are documented in the PR body — the "why" is a required output
(ADR-0012 constraint 4).

**No template match**: the agent does not improvise. It opens an issue describing
the gap, the finding that motivated it, and why no template in the library covers
it, and requests human authorship of a new template.

### Repo layout

```
sources/
  gatekeeper-policies/           # Argo CD source — org-wide base constraints
    kustomization.yaml
    <policy-name>.yaml           # org-wide ConstraintTemplate + Constraint instances

clusters/
  <cluster-name>/
    gatekeeper-policies.yaml     # gate file activating the app; templatePatch may
                                 # set spec.source.path to the overlay below
    gatekeeper-policies/         # per-cluster kustomize overlay (when needed)
      kustomization.yaml
      <policy-name>.yaml         # cluster-specific Constraint additions or patches
                                 # (enforcementAction: dryrun|warn|deny)

schema/
  gatekeeper-templates/          # template library — human-authored, peer-reviewed
    <template-name>/
      constraint-template.yaml   # ConstraintTemplate (Rego included)
      parameters.md              # parameter schema and guidance
```

`sources/gatekeeper-policies/` is the org-wide base: `ConstraintTemplate` resources
and any `Constraint` instances that apply to every cluster. It is a standard Argo CD
source managed by the app-of-apps (ADR-0001, ADR-0003). Per-cluster constraint
instances and kustomize overlays live in `clusters/<cluster-name>/gatekeeper-policies/`,
consistent with the repo's established pattern that all cluster-specific configuration
belongs under `clusters/` (not inside `sources/`). A cluster's gate file
(`clusters/<cluster-name>/gatekeeper-policies.yaml`) activates the app and, when a
cluster overlay exists, uses `templatePatch` to point `spec.source.path` at that
overlay directory. The template library under `schema/` is not directly deployed — it
is the authoritative source from which constraint instances in both locations are
derived. Keeping it separate enforces the distinction between *reusable rule
definitions* (human-owned, peer-reviewed, in `schema/`) and *deployed constraint
instances* (agent-authored, governance-gated, in `sources/` and `clusters/`).

### Enforcement promotion cadence

Every new `Constraint` enters with `enforcementAction: dryrun`. This is not
optional. A policy in dryrun logs violations without blocking workloads, giving
reviewers real data — "N workloads in these namespaces would be blocked" — before
any traffic impact. The promotion cadence is two steps, each requiring a
`human-approval` PR:

1. **dryrun → warn**: non-blocking admission warnings visible to deployers.
   Minimum monitoring window: one week in a non-production environment, or evidence
   that no legitimate workloads are affected.
2. **warn → deny**: enforcing. Minimum monitoring window: one additional week, or
   documented sign-off from the team(s) owning affected namespaces.

The agent monitors violation counts during the dryrun and warn windows and surfaces
the data in the promotion PR. It does not initiate promotion autonomously — it
*proposes* the PR when the window has elapsed and violation counts are acceptable;
a human merges it.

### OKF provenance

Policy PRs carry OKF provenance in the PR body and in the constraint YAML
annotations: which posture-sensor run or RHACS signal triggered the authoring, the
template version used, the parameterization rationale, and violation counts at each
promotion stage. This makes the policy's origin and promotion history browsable
alongside the policy itself, consistent with the knowledge-layer requirement in
ADR-0012.

## Options considered

### Option A — Template-library-first authoring, dryrun-first promotion (chosen)

| Dimension | Assessment |
|-----------|------------|
| Rego correctness | High — no LLM-generated Rego; hallucinations cannot corrupt policy logic |
| Coverage velocity | Medium — bounded by library size, but library grows by PR |
| Human authority | Preserved — every new constraint and every promotion is a `human-approval` PR |
| Fit | High — maps directly onto the ADR-0012 authoring loop and governance lanes |

**Pros:** eliminates the worst failure mode (silent over-permissiveness from
incorrect Rego); dryrun data makes human review meaningful; templates are auditable
and reusable across clusters.
**Cons:** gaps that no template covers require human authorship, which may slow
coverage for novel policy needs; template library is a maintenance surface.

### Option B — LLM generates Rego directly, human reviews

**Pros:** unlimited coverage; no template maintenance burden.
**Cons:** plausible-but-wrong Rego is the core failure mode for security policy,
and human review of Rego is as specialist as authoring it — reviewers may approve
incorrect policies. Rejected as an unacceptable risk given that the consequence is
*silent security gaps*, not visible errors.

### Option C — No agent authoring; maintain Gatekeeper policies manually

**Pros:** no new machinery; full human control of every Rego line.
**Cons:** this is the status quo whose cost — systematic under-investment in
preventive coverage or disproportionate platform-team toil — motivates this ADR.
Rejected as the gap to be addressed.

## Trade-off analysis

The template-library constraint trades **coverage velocity** for **correctness
assurance**. In security policy, correctness is not optional: a rule that is
20% slower to land is better than a rule that silently passes what it should block.
The library also concentrates Rego expertise: peer-reviewed templates are a shared
asset that amortizes authorship cost across all clusters and all policy instances
derived from them. The marginal cost of a new constraint instance is parameterization
and review, not Rego authorship.

The dryrun-first cadence trades **deployment speed** for **blast-radius control**.
A new admission policy that blocks legitimate workloads without warning is a
production incident; one deployed in dryrun for a week is a data-gathering
exercise with no traffic impact. The two-step promotion (dryrun → warn → deny)
also gives teams owning affected namespaces a visible signal and a review window
before enforcement. This matches the flywheel's broader principle: changes that
affect production always take the strictest gate, and that gate is meaningful when
reviewers have data to act on.

## Consequences

**Positive:**

- Preventive and reactive security enforcement become complementary rather than
  alternatives: RHACS detects what escapes the gate; Gatekeeper pushes the gate
  forward so fewer things need detecting.
- Template-library-first authoring closes the "Rego tax" for *constraint instances*
  while keeping human experts on *rule authorship* — the allocation of effort
  matches skill and risk.
- Dryrun-first promotion makes human review substantive: promotion PRs carry
  violation counts, so approval is an informed act, not a rubber stamp.
- OKF provenance gives the policy a browsable history from signal → template →
  parameterization → promotion, co-located with the constraint YAML itself.
- The library grows by PR into `schema/gatekeeper-templates/`, accumulating
  organizational hardening knowledge in a reusable, auditable form.
- RHACS becomes a feedback loop for Gatekeeper coverage gaps, tightening the
  preventive/reactive cycle over time.

**Negative / constraints:**

- The template library is a maintenance surface: templates must be kept current
  with OPA/Gatekeeper API changes and Red Hat hardening guidance. Stale templates
  can produce broken constraints, which is preferable to incorrect ones but still
  a toil cost.
- Coverage is bounded by the library. Novel policy requirements — an org-specific
  rule with no existing template — require human Rego authorship before the agent
  can parameterize an instance. The agent surfaces these gaps but cannot fill them.
- The two-step promotion cadence adds calendar time from identified gap to enforcing
  policy. This is intentional, but it means new enforcement posture takes weeks, not
  hours, to deploy. Security-urgent policies need an expedited lane defined in
  practice (shorter dryrun window, named approver) — this ADR does not prescribe it.
- Every promotion PR is a `human-approval` item. A large estate with many constraints
  in flight adds review load; batching promotions by cluster or policy family is a
  likely operational necessity once the catalog matures.
- `sources/gatekeeper-policies/` and `schema/gatekeeper-templates/` are net-new
  directory surfaces that must be integrated into CI schema validation (ADR-0009).

## Related

- ADR-0012: OpenShift Genesis — agent-owned repository and flywheel governance
  (authoring loop, governance lanes, security and supportability roles, RHACS
  integration, `human-approval` lane definition)
- ADR-0011: Cluster config harvesting (peer sensor in the authoring loop)
- ADR-0013: Agent cost metering and budget governance (policy-authoring runs are
  cost-bearing sensor activity)
- ADR-0009: CI linting and ADR compliance (schema validation must cover
  `sources/gatekeeper-policies/` and `schema/gatekeeper-templates/`)
- ADR-0001: Sources organized by application (`sources/gatekeeper-policies/` follows
  the standard source layout)
- ADR-0003: Organizational defaults over boilerplate (enforcement promotion cadence
  is a default that gate files may not shorten without human-approval)
- [Eliminating the Rego Tax — Red Hat next.redhat.com (2026-03-20)](https://next.redhat.com/2026/03/20/eliminating-the-rego-tax-how-ai-orchestrators-automate-kubernetes-compliance/)
- Red Hat Advanced Cluster Security for Kubernetes (RHACS / StackRox) — runtime
  signal that feeds the posture sensor (ADR-0012)
- OPA Gatekeeper — `ConstraintTemplate` / `Constraint` admission webhook framework
- [Gatekeeper policy library — open-policy-agent/gatekeeper-library](https://github.com/open-policy-agent/gatekeeper-library)
  (upstream reference for template library seeding)
