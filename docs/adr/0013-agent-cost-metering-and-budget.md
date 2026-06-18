# ADR-0013: Agent cost metering and budget governance

- **Status**: Proposed
- **Date**: 2026-06-17

## Context

ADR-0012 positions OpenShift Genesis as a Bring Your Own Agent that consumes Red
Hat AI's operational plane, and explicitly flagged **cost/budget tracking** as the
one capability with no home. AgentOps treats per-run resource and token cost as a
first-class signal — agents that complete tasks *"efficiently, safely, and within
budget constraints."* Genesis has no notion of its own cost today.

This is not cosmetic. The agentic flywheel (ADR-0012) is, by design, a continuously
running set of sensors and review roles that author changes, harvest drift, and
remediate findings without a human initiating each run. Those activities cost real
money: model inference (tokens), paid tool/API calls, and cluster compute. An agent
that loops, or a noisy sensor (ADR-0011 already showed one sensor producing dozens
of candidates per run; RHACS can produce many more), can run up unbounded spend with
no natural backpressure. Nondeterminism makes this worse — the agent cannot perfectly
predict what a task will cost before doing it.

Equally, a hard cap that simply halts the agent is too blunt. A security remediation
(ADR-0012 security role) should not be starved because the documentation sensor
burned the month's budget. And there are legitimate moments where the *right* answer
is to **spend more** — a one-time push to get an urgent change done now, or a
standing increase because demand has durably outgrown the budget. The agent should be
able to *recognize and argue for* that, but never to *authorize the spend itself*.

### Constraints

1. **Budget is declarative, versioned, git-managed config** — like the autonomy
   policy (ADR-0012). It lives in the repo, and any change to it is a spend
   authorization, so it takes the strictest gate (`human-approval`), per ADR-0012
   constraint 5.
2. **The agent meters itself.** Every run attributes its cost (tokens, paid
   tool/API calls, compute) to a task and the sensor/role that triggered it. Cost is
   recorded in OKF provenance and exported to the AgentOps plane — not held in a
   private ledger.
3. **The agent never acquires budget autonomously.** It may *spend within* its
   allocated budget and *request* more, but enabling a one-time top-up or a new
   subscription is always a human act. This is the financial analogue of ADR-0012's
   "the agent can never widen its own authority."
4. **Fail safe, not fail destructive.** When budget is exhausted the agent stops
   *initiating new discretionary work*; it never abandons an in-flight task in a way
   that corrupts state or leaves a half-written PR. Degradation is graceful.
5. **Critical work is not starved by cheap work.** The budget model must let
   high-value lanes (security/supportability remediation) proceed even when
   discretionary lanes (docs, routine drift capture) are spent.

## Decision

Introduce **agent cost metering and a declarative budget policy**, with budget-aware
task prioritization and a human-gated budget-request mechanism. Cost becomes a
first-class input to the authoring loop (ADR-0012), alongside the governance lanes.

### Budget policy

A declarative `budget` policy file lives in the repo next to the autonomy policy
(ADR-0012). It defines, per accounting period (monthly is a sane default):

- A **total ceiling** (in spend and/or tokens) for agent activity.
- **Reserved allocations** per lane/role so critical work cannot be starved — e.g. a
  reserved slice for the security and supportability roles, a separate discretionary
  pool for docs/drift. (Allocations may also be scoped per cluster or per team where
  ADR-0007/team profiles exist.)
- **Thresholds** that trigger agent behavior: a *soft* threshold at which the agent
  begins deferring discretionary work and warning, and the *hard* ceiling at which
  only reserved/critical lanes proceed.

The policy is human-authored and human-approved like any spend authorization; the
agent may *propose* changes to it (see budget requests) but never ratify them.

### Self-metering and attribution

Each agent run records its cost and attributes it to the triggering task and
sensor/role. This rides the observability mechanisms ADR-0012 already establishes:

- **OKF provenance** records gain a cost field — the git-native, auditable slice
  ("this PR's authoring run cost ~N tokens / $X, triggered by the RHACS sensor").
- **AgentOps** (MLflow/OTel) receives the fuller per-run telemetry. Genesis exports;
  it does not carry its own billing backend.

Metering is best-effort against the underlying providers' accounting (model token
counts, paid tool invocations, cluster resource samples) and is itself low-cost.

### Budget-aware prioritization

When the queue of pending work would exceed the remaining budget for the period, the
agent does not run first-come-first-served until it stops. It **ranks** pending tasks
by value and completes the highest-value set that fits the remaining budget,
deferring the rest to a visible backlog (issues / a queue doc), never silently
dropping them. Indicative ranking, highest first:

1. Security and supportability **remediations** (ADR-0012 roles) — funded from
   reserved allocations.
2. Production-affecting corrections and drift capture (ADR-0011).
3. Dev/lab drift capture.
4. Documentation / OKF upkeep.

The ranking is itself policy in the budget file, so it is auditable and tunable by
PR rather than baked into the agent.

### Budget requests — two kinds, both human-gated

When value exceeds available budget, the agent does not silently defer high-value
work; it **makes the case for more budget**, presenting cost/benefit in chat (the
primary UI, ADR-0012) and/or as a request artifact:

- **One-time top-up.** For a specific, time-sensitive high-priority task, the agent
  estimates the marginal cost to complete it *now* and requests a one-time
  allocation: *"This remediation will cost ~$X; you have $Y left this period.
  Approve a one-time $Z top-up to do it now, or defer to next period?"* Human
  approval releases the funds and the agent proceeds immediately. The approval is
  recorded (the top-up is a tracked, audited event).
- **Subscription / standing-budget recommendation.** When the agent observes
  *sustained* demand outrunning the standing budget (trend data from its own
  metering), it recommends an ongoing increase — a larger period ceiling, a new
  reserved allocation, or a new paid subscription/tier — justified with the observed
  trend. This is realized as a *proposed change to the budget policy file*, which
  flows through the normal `human-approval` lane.

Both kinds are the agent **arguing**, the human **deciding**. Constraint 3 holds:
the agent quantifies and recommends; it never authorizes spend.

### Self-reference

The budget policy lives in the repo and is managed by the same flywheel (ADR-0005).
Changes to it route to `human-approval` (ADR-0012), so the agent can no more widen
its own budget than it can widen its own autonomy. The two policies are siblings:
autonomy bounds *what* the agent may do unattended; budget bounds *how much* it may
spend doing it.

## Options considered

### Option A — Declarative budget policy + self-metering + human-gated requests (chosen)

| Dimension | Assessment |
|-----------|------------|
| Complexity | Medium — metering + a classifier-adjacent prioritizer, but reuses ADR-0012 lanes, OKF, and AgentOps export |
| Cost control | Strong — hard ceiling, reserved lanes, graceful degradation |
| Human authority | Preserved — all budget changes are human-approved spend authorizations |
| Fit | High — mirrors AgentOps cost model and ADR-0012's policy-as-config pattern |

**Pros:** bounded, auditable spend; economically rational prioritization; humans keep
spend authority; consistent with existing policy-as-config and governance lanes.
**Cons:** cost estimation is imperfect (nondeterminism); needs provider metering
integration; a too-tight budget can cause prioritization thrash.

### Option B — Hard cap only (halt at ceiling)

**Pros:** trivial to implement; absolute spend guarantee.
**Cons:** starves critical work behind cheap work; no path to spend-more-when-right;
abrupt halt risks leaving work half-done. Rejected — violates constraints 4 and 5.

### Option C — No budget; rely on provider-side billing alerts

**Pros:** zero in-repo machinery.
**Cons:** reactive, not preventive; no attribution, no prioritization, no in-loop
request path; the agent stays cost-blind. Rejected — this is the status quo gap
ADR-0012 flagged.

## Trade-off analysis

The core tension is **bounded spend vs. not starving important work**. A pure cap
(Option B) guarantees the first and fails the second; pure provider billing (Option
C) does neither in-loop. Option A spends its complexity budget precisely on resolving
that tension: reserved allocations and value-ranked prioritization keep critical work
funded under pressure, and the two request paths give a *governed* escape hatch when
the right answer is to spend more — without ever handing the agent the checkbook. The
residual risk is estimation accuracy; we accept it because the requests are
human-decided and the ceiling is hard, so a bad estimate costs a deferral or an extra
review, never an unbounded overrun.

## Consequences

**Positive:**

- Closes the cost gap ADR-0012 named: the agent meters itself, spends within a
  declared budget, and prioritizes economically instead of running until something
  stops it.
- Spend authority stays human, auditable, and git-versioned — budget changes are
  reviewed PRs, top-ups are tracked events, and the autonomy/budget policies are
  siblings under the same strict gate.
- Cost attribution rides existing rails (OKF provenance + AgentOps export), so cost
  becomes browsable alongside the *why* of each change.
- The agent can advocate for more budget — one-time or ongoing — turning "we're out
  of budget" from a silent stall into an explicit, justified, human decision.

**Negative / constraints:**

- Cost estimation for a nondeterministic agent is inherently imprecise; marginal-cost
  quotes in budget requests are estimates, and reserved allocations need tuning to
  avoid both starvation and waste.
- Metering depends on provider-side accounting (model token counts, paid-tool
  billing, compute sampling) that must be wired up; coverage will be partial at first.
- A too-tight or badly-partitioned budget can cause prioritization thrash or defer
  work that mattered — the ranking policy will need iteration in practice.
- **Subscription recommendations edge into procurement**, which has organizational
  process beyond this repo. The agent's output here is a *recommendation with
  evidence*; acting on it (signing up, paying) remains an out-of-band human/finance
  step, and the ADR deliberately stops at the recommendation boundary.
- Net-new machinery (metering, prioritizer, request flow) to build and operate; it
  should be staged — metering and reporting first, hard ceiling next, prioritization
  and budget requests last.

## Related

- ADR-0012: OpenShift Genesis — agent-owned repository and flywheel governance
  (BYOA/AgentOps alignment; autonomy policy this budget policy is a sibling of)
- ADR-0011: Cluster config harvesting (a cost-bearing sensor)
- ADR-0005: Flywheel self-reference (budget policy is self-managed)
- ADR-0008: Branch protection and repository governance (budget changes are PRs)
- ADR-0007: Cluster classification (per-cluster/per-env budget scoping)
- [AgentOps (Red Hat)](https://www.redhat.com/en/topics/ai/agentops) — per-run cost
  as a first-class signal
