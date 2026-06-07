# profiles/

Organizational profiles — Argo CD Applications with organizational significance.
Profiles encode reusable, composable configuration that would otherwise be
copy-pasted across teams or clusters.

A profile is just a `sources/<app>` with a well-known organizational meaning.
It is deployed to a cluster like any other app, via a gate file in `clusters/<cluster>/`.

## Subdirectories

| Directory | Purpose |
|---|---|
| [`teams/`](teams/) | Per-team configuration: AppProject definitions, default namespaces, team-specific app sources |
| [`cluster-types/`](cluster-types/) | Cluster-type profiles: canonical app compositions for each cluster class |
| [`data-centers/`](data-centers/) | Data-center overrides: network, storage class, and infrastructure-specific defaults |

## Cluster-types and app-groups

A **cluster-type** is a profile that declares the canonical set of apps for a class
of cluster (e.g., `sno`, `hub`, `app`). Each cluster has exactly one cluster-type.

A **cluster-type** is composed from one or more **app-groups** — reusable,
independently deployable collections of apps. App-groups live under
[`cluster-types/app-groups/`](cluster-types/app-groups/) and can be shared across
cluster-types.

Example: the `hub` cluster-type might include `platform-base` and `hub-networking`
app-groups. A primary hub and secondary hub are the same cluster-type with different
app-group compositions — not two separate cluster-types.

## Related ADRs

- [ADR-0003](../docs/adr/0003-organizational-defaults-over-boilerplate.md) — cascade layers
- [ADR-0007](../docs/adr/0007-cluster-naming-convention.md) — cluster-type definitions
