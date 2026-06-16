# ADR-0003: Organizational defaults over boilerplate

- **Status**: Accepted
- **Date**: 2026-06-03

## Context

In a GitOps repo shared across many teams and applications, every app team must
configure the same recurring concerns: which AppProject owns the app, where it
deploys, what sync policy to use, what RBAC roles apply, and so on. If each team
writes this configuration from scratch, the repo accumulates large amounts of
structurally identical YAML that is hard to keep consistent and expensive to change
org-wide (e.g., adding a new sync option, tightening an RBAC policy).

Two common failure modes:

1. **Copy-paste boilerplate**: Teams copy a working example and modify it. Drift
   accumulates. Org-wide changes require mass edits.
2. **Over-specified overrides**: Teams specify everything explicitly to be safe,
   making it impossible to tell which values are intentional deviations vs. noise.

The root cause is the same: no authoritative org default exists, so teams are forced
to be explicit about everything.

## Decision

Every value that this repo governs has an authoritative organizational default.
Teams only write what genuinely deviates from that default. Kubernetes field
defaults (restart policies, resource limits, etc.) are Kubernetes's concern, not
this repo's — we only declare defaults for the concerns we own.

### Configuration cascade

Configuration resolves through layers, similar to CSS cascade. Each layer only
needs to specify what differs from the layer below. Higher layers win.

```
Layer 4 — Per-cluster-per-app gate file   clusters/<cluster>/<app>.yaml
Layer 3 — Profile overrides               profiles/teams/, profiles/cluster-types/,
                                           profiles/data-centers/
Layer 2 — Org defaults                    sources/app-of-apps/ template,
                                           sources/app-projects/chart/values.yaml
Layer 1 — Kubernetes / Argo CD defaults   (outside this repo's scope)
```

Layers 2 and above are within this repo. There is no fixed limit on the number
of profile layers — a team may apply multiple profiles (e.g., a cluster-type
profile and a team profile) each contributing a subset of overrides.

Defaults are declared in exactly one place per concern:

| Concern | Org default location |
|---|---|
| Argo CD Application fields | `sources/app-of-apps/applicationset.yaml` template |
| AppProject RBAC structure | `sources/app-projects/chart/values.yaml` |
| Team / cluster-type / data-center profiles | `profiles/` |

Overrides are always additive — a team that needs a non-default destination, sync
policy, or RBAC rule adds only the differing fields. The absence of a field means
"use the layer below," never "undefined."

### ApplicationSet defaults

The app-of-apps ApplicationSet provides defaults for every Application field.
Per-app config files (`clusters/<cluster>/<app>.yaml`) are optional. An empty or
absent file signals "use all defaults." The `templatePatch` mechanism allows any
Application field to be overridden without a fixed schema — teams have complete
freedom to express any Argo CD Application configuration without adding generator
variables to the ApplicationSet.

Differences in `spec.source.repoURL`, `spec.source.targetRevision`,
`spec.source.path`, and `spec.syncPolicy` are ignored by Argo CD so that teams can
make ephemeral changes in the UI (e.g., pointing at a development branch) without
triggering a revert on the next sync.

### AppProject defaults

AppProject configuration is expressed as a locally-contained Helm chart
(`sources/app-projects/chart/`). The chart encodes the org's RBAC structure (three
roles per team: admins/developers/viewers mapping to OpenShift admin/edit/view),
default source repos, and default destinations. A per-team values file
(`sources/app-projects/<team>.yaml`) provides only the team-specific data — team
name, LDAP groups, and any deviations from defaults.

Adding a new AppProject is two files: `sources/app-projects/<team>.yaml` and a line
in the `clusters/<cluster>/app-projects.yaml` valueFiles list.

## Consequences

**Positive:**

- A new app is a single empty file in `clusters/<cluster>/`. No boilerplate. (A missing file means the app is not deployed to that cluster.)
- A new AppProject is a minimal values file. No RBAC boilerplate.
- Org-wide policy changes (new sync option, updated RBAC structure) are made in one
  place and propagate automatically.
- Explicit overrides stand out — if a field is present in a per-app or per-team
  config, it is intentionally different from the org default.
- Forward compatibility: the `templatePatch` escape hatch means the ApplicationSet
  never needs to be extended to support new Argo CD Application fields.

**Negative / constraints:**

- Teams must understand what the org defaults are to know when to override. Defaults
  must be well-documented (in this ADR and in the ApplicationSet/chart comments).
- A wrong org default affects all apps/projects simultaneously. Changes to defaults
  require careful review.
- The Helm chart approach for AppProjects means Helm is a required tool for
  rendering `sources/app-projects/`. This is acceptable: Argo CD supports Helm
  natively, and the chart is locally contained with no external dependencies.

## Related

- `CLAUDE.md` — Content Generation section
- ADR-0001: Organize sources by application, not delivery tool
- ADR-0002: Application naming convention
- `sources/app-of-apps/applicationset.yaml` — ApplicationSet defaults
- `sources/app-projects/chart/values.yaml` — AppProject defaults
