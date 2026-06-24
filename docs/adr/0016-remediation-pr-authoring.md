# ADR-0016: Sensor-driven remediation PR authoring

- **Status**: Proposed
- **Date**: 2026-06-18

## Context

The ADR-0012 authoring loop defines a general pattern — sensors → agent authors
change → branch + PR → CI → governance lane — but treats remediation as one case
among many without naming it. The pattern has become a first-class subject because
the market has moved: Akuity (AI Agent) and Harness (agentic layer) now ship
autonomous remediation for Argo CD in production. Both monitor Argo CD
`OutOfSync` / `Unhealthy` states, perform resource-tree root-cause analysis, and
open a PR to fix the problem (image rollback, resource limit adjustment). This is
the autonomous-remediation primitive from the salience engine's cross-domain
analysis (pass 002–004).

The question this ADR addresses: **should Genesis delegate remediation-PR
authoring to one of these vendors, or build and own the pattern natively?**

The answer is to own it natively. The case follows from a single observation:
**Akuity and Harness are bounded by Argo CD's managed-resource view.** They can
only detect and remediate drift in resources that are already declared in an Argo
CD Application. Genesis's sensor framework is structurally broader:

| Sensor | What it sees | In Argo CD's view? |
|---|---|---|
| Config-harvester (ADR-0011) | Unmanaged cluster resources — the entire surface Argo CD *does not yet own* | No |
| Argo CD drift | `OutOfSync` / `Unhealthy` for managed resources | Yes |
| RHACS | CVEs, policy violations, misconfigurations across all cluster resources | Partial |
| Supportability role | Unsupported configuration in any proposed or harvested manifest | No |
| Operator channel availability | New versions in subscribed channels | No |

The harvest sensor — the differentiator — exists precisely *because* Argo CD's
reconciler is one-directional: it drives managed resources toward git, but has no
facility to discover the unmanaged surface or bring it into the flywheel. Delegating
to Akuity/Harness would abandon the harvest sensor's entire value proposition: the
ability to close the loop on config that has never been in git.

Additional reasons to own the pattern natively:

- **Multi-sensor composition.** A single PR may be triggered by overlapping signals
  (a harvested resource that also has an RHACS finding should produce one composed
  PR, not two competing vendor PRs that step on each other).
- **OKF context.** Genesis knows what a correct config *should* look like for this
  organization — not just what git currently says. The OKF knowledge graph (ADR-0012)
  provides organizational standards, team ownership, and app relationships that
  vendor agents do not have access to.
- **Documentation is a required output.** ADR-0012 constraint 4: a change that does
  not update the affected OKF docs and knowledge records is incomplete. Vendor agents
  do not carry this obligation; their PRs would produce undocumented changes by
  design.
- **Unified governance.** ADR-0012's autonomy policy classifies every PR — including
  remediation PRs — into `auto-merge` or `human-approval` lanes using the same
  classifier. Running a vendor agent alongside Genesis would introduce a second,
  conflicting merge-authorization surface.
- **Red Hat Agentic Skills Repository.** Announced at Red Hat Summit 2026 and
  published at `catalog.redhat.com/en/ai`: curated skill packs encoding institutional
  knowledge (CVEs, patch advisories, product lifecycles) as governed, reusable agent
  behaviors. Genesis's OKF knowledge layer is the organizational analogue of this
  catalog. As the Skills Repository matures, Genesis's remediation skills should be
  evaluated for alignment with the catalog standard — not as a dependency, but as a
  publication target that makes Genesis's remediation knowledge reusable and
  discoverable by the Red Hat ecosystem.

## Decision

Genesis implements its own **sensor-driven remediation PR authoring loop**, native
to the authoring loop defined in ADR-0012. Vendor remediation agents (Akuity,
Harness) are not adopted; their pattern is acknowledged as a reference for the Argo
CD drift sensor specifically.

### The remediation loop

The remediation loop is the authoring loop (ADR-0012) specialized for the case
where the triggering sensor is a *detected deviation* (drift, violation, or
gap) rather than a human instruction:

```
 sensor detects deviation
        │
        ▼
 agent root-causes
        │
        ├─► compose PR:
        │     • manifest fix (the change)
        │     • OKF record update (the why)
        │     • PR body: sensor signal, root-cause, fix rationale
        │
        ▼
 CI + governance lane (ADR-0012)
        │
        ├─► auto-merge  (narrow allowlist)
        └─► human-approval (default)
```

Each sensor feeds this loop with a different class of deviation:

**Harvest sensor (ADR-0011) — unmanaged drift.**
The highest-value remediation signal. A resource on a running cluster that is not
managed by any Argo CD Application is a gap between the cluster's real state and the
flywheel's authority. The remediation PR brings the resource into `sources/<app>/`
so Argo CD can adopt it. This sensor operates entirely outside Argo CD's view and
cannot be replicated by vendor agents built on the Argo API.

**Argo CD drift — managed resource deviation.**
An `OutOfSync` or `Unhealthy` application where the live state has diverged from
the desired state in git. Unlike vendor agents, Genesis's response is not limited to
rolling back the live resource: if the deviation indicates the git config is wrong
(e.g., a resource limit that is consistently manual-overridden in production),
Genesis can propose a git update to canonicalize the intended state, routed to
`human-approval` because a production cluster is in scope.

**RHACS sensor — security-driven remediation.**
CVEs, deploy-time policy violations, and compliance failures from RHACS trigger
remediation PRs: pin or bump a vulnerable image tag, tighten a `SecurityContext`,
add a missing `NetworkPolicy`, narrow over-broad RBAC. Security findings always
route to `human-approval` (ADR-0012 constraint 8). The RHACS baseline itself is
git-managed (`sources/rhacs/`), so the policy set that triggers remediation is
itself a flywheel artifact.

**Supportability role — unsupported configuration.**
The supportability gate (ADR-0012) detects config that risks falling outside Red
Hat's supported-configuration boundaries. When harvest or authoring surfaces such
config, the remediation PR proposes the supported alternative and explains why, or
opens a tracking issue if no supported alternative exists. Supportability findings
always route to `human-approval`.

**Operator channel / version sensor — version remediation.**
When a subscribed operator channel publishes a new version, Genesis can propose
updating the subscription (or a production gate file pin) via a remediation PR.
Prod pins route to `human-approval`; dev/lab updates may qualify for `auto-merge`
once the allowlist matures.

### PR composition rules

A remediation PR carries three required elements:

1. **The manifest change** — the minimum diff that closes the detected deviation.
   Genesis does not bundle unrelated cleanup into a remediation PR; focus and
   reviewability are more important than efficiency.
2. **OKF record update** — the affected `sources/<app>/index.md` or
   `clusters/<cluster>/index.md` is updated to reflect the change and record the
   sensor that triggered it (`sensor: harvest|argo-drift|rhacs|supportability`).
   This is not optional; ADR-0012 constraint 4 applies.
3. **PR body** — written for a human reviewer: what sensor fired, what it found,
   why this fix closes the deviation, and what the reviewer should verify. Vendor
   remediation PRs are terse; Genesis's are explanatory.

**Multi-sensor composition.** When two or more sensors flag the same resource in
the same harvester run, Genesis opens a single composed PR rather than one per
sensor. The PR body lists all signals; the governance lane is the *strictest* lane
of any contributing sensor (e.g., a harvest + RHACS finding routes to
`human-approval` even if the harvest portion alone would qualify for `auto-merge`).

### Relationship to the Red Hat Agentic Skills Repository

Genesis's remediation logic — the harvest heuristics, the RHACS policy map, the
supportability ruleset — is maintained as OKF reference records (ADR-0012). These
records are the organizational form of what Red Hat's Skills Repository calls "skill
packs." As the Skills Repository matures:

- Genesis's remediation skills should be evaluated for publication against the
  catalog standard (`catalog.redhat.com/en/ai`), making them reusable and
  discoverable by the broader Red Hat ecosystem.
- Conversely, published Red Hat skill packs (e.g., CVE response patterns, RHEL
  subscription advisory handling) should be evaluated for adoption into Genesis's
  OKF bundle rather than re-derived locally.

The OKF bundle is Genesis's local, git-native skill-pack store. The Red Hat catalog
is the ecosystem publication surface. The two are compatible by design (both are
governed, versioned, auditable records); neither requires adopting the other's
runtime.

## Consequences

**Positive:**

- Genesis's remediation loop covers the full cluster surface — managed and
  unmanaged resources — that no Argo CD–bounded vendor agent can reach. The harvest
  sensor's value is preserved rather than abandoned.
- Multi-sensor composition produces a single coherent PR per deviation rather than
  competing vendor PRs on the same resource.
- Documentation and provenance are first-class outputs of every remediation PR;
  the OKF record tracks which sensor drove which change.
- Governance is unified: every remediation PR passes through the same classifier
  and lane policy as human-authored changes. No second merge-authorization surface.
- The OKF remediation records are a natural candidate for publication to the Red Hat
  Agentic Skills Repository catalog, giving Genesis institutional reach beyond the
  single org.

**Negative / constraints:**

- Genesis must maintain the remediation logic for all four sensor types rather than
  delegating to vendor tooling. This is a significant engineering surface: harvest
  heuristics, RHACS integration, supportability ruleset, and channel monitoring all
  require upkeep as OpenShift versions and Red Hat product guidance evolve.
- Vendor agents (Akuity, Harness) benefit from their own R&D investment in Argo CD
  root-cause analysis and PR quality. Genesis's Argo CD drift sensor will initially
  be less sophisticated than a dedicated vendor agent for that specific signal. The
  trade-off is breadth (all four sensors, unified governance) over depth on the Argo
  CD signal.
- Multi-sensor composition logic adds complexity: correctly attributing a PR to
  multiple sensors, applying the strictest-lane rule, and de-duplicating overlapping
  findings requires careful implementation.
- The supportability ruleset is a maintenance burden that can never be exhaustive
  (see ADR-0012 consequences). The same caveat applies here: the ruleset is a
  high-recall advisor, not an authority.
- PR volume may be high during an initial harvest or a cluster with significant
  accumulated drift. Rate limiting and PR batching (noted in ADR-0012) are essential
  from day one.

## Related

- ADR-0011: Cluster config harvesting (the harvest sensor)
- ADR-0012: Agent-owned repository and flywheel governance (the authoring loop;
  governance lanes; supportability and security review roles)
- ADR-0013: Agent cost metering and budget governance
- ADR-0014: AI-assisted admission control policy authoring
- [Red Hat Agentic Skills Repository (The New Stack, Summit 2026)](https://thenewstack.io/red-hat-agentic-skills-repository/)
- [Red Hat Ecosystem Catalog — AI skills](https://catalog.redhat.com/en/ai)
- [Akuity — AI agents for GitOps operations](https://akuity.io/blog/beyond-dashboards-ai-agents-for-gitops-operations)
- [Harness — AI for GitOps: tame your Argo sprawl](https://www.harness.io/blog/ai-for-gitops-tame-your-argo-sprawl)
- RHACS (Red Hat Advanced Cluster Security) — security sensor, delivered as
  `sources/rhacs/`
