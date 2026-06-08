# Configuration Cascade

> **Zoom level:** Values — how defaults resolve through layers.
> **Previous:** [← App-of-Apps Internals](03-app-of-apps.md) | **Next:** [Ownership Model →](05-ownership.md)
> **ADR:** [ADR-0003 — Organizational defaults over boilerplate](../adr/0003-organizational-defaults-over-boilerplate.md)

Configuration resolves through layers, like CSS cascade. Higher layers win;
a missing value falls through to the layer below. Only write what genuinely
deviates from the layer beneath you.

![Configuration Cascade](img/04-configuration-cascade.svg)

> Source: [`src/04-configuration-cascade.d2`](src/04-configuration-cascade.d2) — render with `make` in this directory.

## What each layer owns

| Layer | Owns | Does NOT own |
|---|---|---|
| **Kubernetes** | Pod spec defaults, K8s API behavior | Org policy |
| **Org defaults** | Sync policy, naming, RBAC template, default destination, default project | Per-team customization |
| **Profile** | Team RBAC specifics, cluster-type app set, DC infrastructure vars | Individual app overrides |
| **Gate file** | Per-cluster-per-app deviations, revision pinning | Everything a higher layer already covers |

## Practical examples

```
Q: What namespace does my-app deploy to?
A: Check gate file → profile → org default (openshift-gitops).

Q: What AppProject does my-app belong to?
A: Check gate file (spec.project) → org default (platform).

Q: Which clusters run my-app?
A: Any cluster with clusters/<cluster>/my-app.yaml present.
```
