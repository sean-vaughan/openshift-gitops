# sources/

Argo CD Application sources — one directory per application.

Each `sources/<app-name>/` is the stable unit of configuration for one application
(ADR-0001). It must be a valid Argo CD source (plain manifests, Kustomize, or Helm)
and may also be consumed by Ansible, RHACM PolicyGenerator, or other delivery tools.
Configs are organized by application, never by delivery tool.

## Deploying a source to a cluster

Touch `clusters/<clusterName>/<app-name>.yaml`. The ApplicationSet picks it up
on the next git poll. An empty gate file uses all org defaults; add fields to
override any Application property.

## Contents

| Source | Type | Purpose |
|---|---|---|
| [`app-of-apps/`](app-of-apps/) | ApplicationSet | Generates all Argo CD Applications — the flywheel |
| [`app-projects/`](app-projects/) | Helm chart | Generates Argo CD AppProjects from team profiles |

## Adding a source

1. Create `sources/<app-name>/` with valid Argo CD content.
2. Add a gate file `clusters/<cluster>/<app-name>.yaml` to deploy it.
3. No other changes required — the ApplicationSet discovers it automatically.

## Related

- [ADR-0001](../docs/adr/0001-sources-by-app.md) — why sources are organized by app
- [ADR-0003](../docs/adr/0003-organizational-defaults-over-boilerplate.md) — org defaults and cascade
- [ADR-0006](../docs/adr/0006-development-workflow-and-environment-promotion.md) — dev loop
