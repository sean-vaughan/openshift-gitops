# ADR-0017: Loop engineering and the autonomous-decision review role

- **Status**: Proposed
- **Date**: 2026-06-19

## Context

ADR-0012 defines the Genesis authoring loop (sensors → agent authors change →
branch + PR → CI → governance lane) and two standing review roles that gate the
*config the agent writes*: the Red Hat Support Agent (supportability) and the Red
Hat Security Operations role (RHACS). ADR-0016 specializes the loop for remediation.

What none of those name is a role that reviews the agent's **own decisions** — the
question an operator instinctively asks of any autonomous system: *"who checks the
AI's thinking before it acts, and who finds its recurring mistakes after?"* This
ADR answers that, and it deliberately answers it in a way that resists the obvious
but corrosive implementation.

### The four-loop frame

LangChain's *The Art of Loop Engineering* gives a clean ladder for agent systems,
and Genesis already lives on it:

| Loop | LangChain definition | Genesis equivalent |
|---|---|---|
| **L1 — Agent** | Model calls tools in a loop until done | The Genesis authoring agent (ADR-0012) |
| **L2 — Verification** | Output scored against a rubric, retried on failure | CI (ADR-0009) + governance-lane classifier + **Verifier** (this ADR) |
| **L3 — Event-driven** | Events trigger agent runs against a real system | The sensor framework (ADR-0011, ADR-0016); EDA |
| **L4 — Hill-climbing** | Production traces feed an analysis agent that improves the harness | The **Auditor** (this ADR) + OKF/drift pipeline |

The hill-climbing efficacy claim ("each outer cycle makes the inner loops more
effective") is asserted by the source, not benchmarked; Genesis adopts the *shape*
of L4, not a promised return curve.

### The hazard this role must not become

The intuitive ask — "review the AI's thinking for errors, and its decisions for
simplicity and consistency" — names the three criteria that, applied to a *reasoning
trace*, turn a reviewer into a **fluency amplifier**:

1. **Errors in thinking.** A trace is not a faithful record of the computation. A
   correct action can carry a confabulated trace; a wrong action can carry an
   immaculate one. Grading the story grades the wrong variable.
2. **Simplicity.** A clean, linear trace is *more* suspect, not less. A capable model
   may reach a correct action by a magical shortcut earned from vast training, with no
   legible chain at all. We want to **harvest those shortcuts, not tax them into
   narration** — forcing a non-verbal policy to explain itself corrupts the next shot
   and slows the path to real-world effect.
3. **Consistency.** The sharpest edge. Enforcing consistency *with the agent's past
   decisions* inverts the prime directive (drift outranks contradiction): the day the
   cluster behaves differently, the correct move is to be *inconsistent* with yesterday.
   A naive consistency-checker suppresses exactly the signal worth surfacing.

The role is valuable; its default implementation is corrosive. This ADR holds the
difference with one rule: **grade contact, never narrative; gate on reversibility,
never legibility.**

## Decision

Genesis adds a third standing review role to the two in ADR-0012, specified as **two
jobs under one charter** that live in different loops. Conflating them is the primary
design error.

| | **Verifier** | **Auditor** |
|---|---|---|
| Loop | L2 (verification) | L4 (hill-climbing) |
| Hot path? | Yes — blocking | No — async / batch |
| Reads | the *result* | the *trace corpus* + the ADRs |
| Grades against | ground truth (cluster, policy, RHACS, SLO) | population-level patterns; recorded ADR commitments |
| Job | let a single action commit safely | find recurring failure patterns; propose harness/ADR changes |
| Output | pass/fail + the approvable artifact | drift flags, simplification finds, surfaced to a human |

The **Verifier never reads reasoning to decide.** The **Auditor reads reasoning only
forensically**, after a contact failure, never to gate a live action. Neither role is
ever realized as an inline per-step reasoning critic — that adds an LLM round-trip to
MTTR and grades narrative quality, the one thing this ADR forbids.

### The four-check stack

Trust in an autonomous decision is not a one-time blessing of a shortcut; it is
**continuous re-contact** — the shortcut stays trusted exactly as long as the world
keeps validating it. The stack arranges that re-contact cheaply, placing friction only
where the world starves the loop of data on its own.

```
  OOD / novelty (LEADING) → dry-run / canary (MANUFACTURED CONTACT)
        → outcome grader (LAGGING) → auditor (FORENSIC)
```

1. **OOD / novelty gate — leading.** Before acting: *is this input inside the support
   of my evidence?* A question about the input distribution, answerable without
   legibility. Catches the spatial tail (wandered off the validated manifold).
2. **Reversibility / blast-radius gate — manufactured contact.** The *only* axis that
   earns friction. Reversible (read-only diagnosis, reversible Argo sync) runs at full
   speed — being wrong is cheap and the miss *is* the learning signal. Irreversible /
   tier-zero (e.g. a destructive change against a RAN function) routes to **dry-run /
   canary / staged apply**, making the outcome arrive *before* the commitment. The gate
   is an epistemic instrument, not a safety brake. Catches the temporal tail.
3. **Outcome grader — lagging.** After acting: did the world validate it? Cluster
   reconciled, SLO recovered, RHACS clear, policy passed, no ADR contradicted. Grades
   the *landing, not the trajectory* — the shortcut's speed is untouched.
4. **Auditor — forensic.** Async, over the logged trace corpus: recurring
   reasoning-failure patterns, places a *simpler* decomposition would have worked,
   drift between field behavior and the ADRs. Proposes changes; never auto-applies.

### Refinement to ADR-0012's governance classifier

ADR-0012 classifies PRs into `auto-merge` / `human-approval` lanes primarily by
changed-path globs plus security-sensitive kinds. This ADR refines that: the
load-bearing axis is **reversibility / blast-radius**, with path and kind as proxies.
Dev/lab and read-only or reversible changes are auto-merge candidates at full speed;
irreversible or tier-zero changes take manufactured contact (dry-run/canary) and the
`human-approval` lane. Security-sensitive content remains `human-approval` regardless
(ADR-0012 constraint 8). This is a clarification of the existing lanes, not a widening
of auto-merge.

### Consistency is checked against two things only

The Verifier and Auditor check consistency against **ground truth** (current
cluster/policy/telemetry state) and **the ADRs** (intentional, recorded commitments —
e.g. "does this contradict ADR-0012's identity model or ADR-0013's budget policy?").
They must **not** check consistency against the agent's own prior outputs.
Inconsistency-with-reality is the find; inconsistency-with-yesterday is often the
correct response to drift.

### The Auditor's corpus includes PR-review outcomes

The richest ground-anchored signal Genesis already produces is what *humans do to its
PRs*. Reviewer comments, change-requests, lane-overrides (a human moving a PR the
classifier put in `auto-merge` to `human-approval`, or the reverse), and post-merge
reverts are first-class **Auditor** inputs — they are the world acting on the agent's
output at the PR boundary, the human-checkpoint realization of the outcome grader. They
join the audit / Argo / EDA trace corpus the Auditor mines (L4, async).

Two disciplines bound this so it does not regress into the hazard above:

- **Read PR feedback as contact, never as a narrative score.** A human rejecting or
  fixing a harvested manifest is contact — *the output was wrong about the world*. The
  agent's own drafted PR prose (commit message, PR body) is narrative and is **not**
  graded for fluency, simplicity, or consistency; at most it is read *forensically*
  after a contact failure (a revert), never as a standing quality metric.
- **Overrides and reverts are labeled signal for the harness, not for the agent's
  self-image.** A path-class humans repeatedly pull out of `auto-merge` is a proposed
  change to the allowlist or the harvest heuristics — the hill-climbing loop closing —
  surfaced for human ratification, never an auto-applied widening of the agent's own
  authority (ADR-0012 constraint 5). Consistency is still measured against ground truth
  and the ADRs (above), not against the agent's prior PRs.

This names an input class; it is not a new mechanism. The Verifier (L2, hot path) is
unaffected — PR-review mining is strictly the Auditor's async, forensic job.

## Consequences

**Positive:**

- Genesis gains the missing L4 loop without bolting on an inline reasoning critic that
  would tax MTTR and select for confabulation.
- The reviewer is cheap and ground-anchored, which closes the "who reviews the
  reviewer" regress at the cheapest rung: *the cluster does* — not a bigger critic.
- The reversibility axis simplifies the ADR-0012 classifier to the variable that
  actually carries risk, and lets reversible dev/lab changes move fast.
- The Auditor folds into the existing OKF/drift-flag pipeline (ADR-0012, ADR-0016)
  rather than adding a new surface.

**Negative / constraints:**

- The regress does not fully close. The OOD detector can be confidently wrong about
  novelty — the same failure one rung up. Each rung is *cheaper and more
  ground-anchored*, not certain. The deliverable is **fails gracefully, recovers
  fast**, never "guaranteed correct."
- The Verifier's value depends entirely on having real deterministic graders (cluster
  state, RHACS, SLO, ADR-conflict). Where ground truth is weak or delayed, the L2 gate
  degrades and more weight falls on the human lane.
- Reversibility classification of the action set is itself non-trivial and must be
  conservative (unknown → treat as irreversible).

## Implementation status

- **MVP (this phase):** L1 agent + minimal L2 (CI + human gate). This ADR — the role
  is specified.
- **Post-MVP (live-cluster engineering, not fabricable from a design doc):**
  reversibility classifier over the action set; dry-run / canary harness for the
  irreversible class; deterministic outcome graders + ADR-conflict check; OOD pre-gate;
  the async Auditor over audit + Argo + EDA + PR-review (comments, change-requests,
  lane-overrides, reverts) trace history. Items fold into the ADR-0016 sensor framework
  and the OKF drift pipeline.

## Related

- ADR-0009: CI linting and ADR compliance (the deterministic floor of L2)
- ADR-0011: Cluster config harvesting (an L3 sensor)
- ADR-0012: Agent-owned repository and flywheel governance (the authoring loop; the
  two existing review roles this ADR joins; the governance lanes this ADR refines)
- ADR-0013: Agent cost metering and budget governance (a recorded commitment the
  reviewer checks against)
- ADR-0016: Sensor-driven remediation PR authoring (the L3/L4 loop this role reviews)
- [LangChain — The Art of Loop Engineering](https://www.langchain.com/blog/the-art-of-loop-engineering)
- [Anthropic — Project Fetch: Phase Two](https://www.anthropic.com/research/project-fetch-phase-two)
  (the legible/plannable layer accelerates ~19× and uses ~10× less code; the
  below-language control task still fails — the speedup and the failure are the same
  finding read from two sides)
- [From Augmentation to Symbiosis (arXiv:2601.06030)](https://arxiv.org/abs/2601.06030)
  (human-AI pairs win on problem formulation, lose on low-level control — the reviewer
  must not invert this by demanding a legible layer it cannot have)
