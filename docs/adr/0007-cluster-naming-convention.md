# ADR-0007: Cluster naming convention

- **Status**: Accepted
- **Date**: 2026-06-03

## Context

Cluster names appear in many places: Argo CD Application names, RHACM
`ManagedCluster` objects, gate file paths (`clusters/<clusterName>/`), dashboard
labels, alerts, and runbooks. A cluster name that carries no information forces
operators to look up a cluster's role, location, and environment from an external
registry. A name that is too verbose is painful in Application names and `kubectl`
output.

Cluster names must also be:

- DNS-compatible (RFC 1123): lowercase, alphanumeric, hyphens only, ≤ 63 characters
- Stable: renaming a cluster requires renaming every Application, gate file, and
  ManagedCluster object that references it
- Unique within the organization

## Decision

All cluster names follow the pattern:

```
<dc>-<type>-<env>-<n>
```

| Segment | Meaning | Examples |
|---|---|---|
| `dc` | Data center or cloud region short code | `rdu`, `chi`, `phx`, `use1`, `euw1` |
| `type` | Cluster type (see ADR profiles/cluster-types/) | `sno`, `mgmt`, `app`, `hub` |
| `env` | Environment | `dev`, `tst`, `prd` |
| `n` | Sequence number within the DC+type+env tuple | `1`, `2`, `3` |

Examples:

- `rdu-sno-dev-1` — first dev Single Node OpenShift cluster in the Raleigh DC
- `chi-mgmt-prd-1` — first prod management cluster in Chicago
- `use1-hub-prd-1` — first prod hub cluster in AWS us-east-1
- `rdu-app-tst-2` — second test application cluster in Raleigh

### Relationship to RHACM labels

The name encodes identity. Classification for policy targeting is carried by
RHACM `ManagedCluster` labels — the name is not parsed programmatically. The
following standard labels mirror the name segments for RHACM placement rules:

```yaml
metadata:
  labels:
    gitops.openshift.io/data-center: rdu
    gitops.openshift.io/cluster-type: sno
    gitops.openshift.io/environment: dev
```

### Exceptions and lab clusters

Lab or personal clusters that do not fit the production taxonomy may use a free-form
name (e.g., `k8s-sno` for a local development SNO instance). Such clusters are not
subject to this convention but should not be promoted to shared environments without
being renamed to the standard pattern.

### Per-cluster Argo CD vs hub

Cluster names are the same regardless of whether the cluster is managed by its own
Argo CD instance or by a hub. The naming convention is forward-compatible: a cluster
named `rdu-sno-dev-1` with a per-cluster Argo CD today can be onboarded to a hub
Argo CD tomorrow without renaming anything (per ADR-0004).

## Consequences

**Positive:**

- Cluster identity is self-documenting in every context where the name appears.
- RHACM placement rules and Argo CD cluster selectors can use labels, keeping the
  name stable even if an organizational taxonomy changes.
- The 4-segment format is short enough for readable Application names
  (`rdu-sno-dev-1---platform---rbac`) while still being descriptive.
- Forward-compatible with hub Argo CD migration.

**Negative / constraints:**

- Cluster names are chosen at bootstrap time and are expensive to change.
  Organizational alignment on DC codes and cluster-type names is required before
  the first cluster of each type is bootstrapped.
- The `n` sequence is per `dc+type+env` tuple, not globally unique. Tooling that
  needs global uniqueness uses the full name, not just `n`.

## Related

- ADR-0002: Application naming convention
- ADR-0004: Named cluster secrets
- `profiles/cluster-types/` — cluster-type profile definitions
- `CLAUDE.md` — Clusters section
