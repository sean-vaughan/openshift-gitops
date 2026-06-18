# openshift-gitops

## Summary

This repo is the source of truth for OpenShift GitOps — a Kubernetes configuration
"flywheel" that drives Argo CD, RHACM, and related tooling across all clusters in the
organization. A strict, schema-validated directory structure lets an app-of-apps
ApplicationSet derive Argo CD Application boilerplate directly from the repo layout,
with overrides supported at every level.

Every app belongs to an AppProject. Every AppProject is owned by one or more teams.
Teams come from LDAP groups and map to OpenShift `admin`/`edit`/`view` RBAC roles,
reflected into AppProject permissions. Clusters are defined by data-center,
cluster-type, environment, and a unique sequence ID — not as snowflakes.

The `sources/<app-name>` directories are the primary unit of deployment. Each is a
valid Argo CD Application source and may also be consumed by Ansible, RHACM
PolicyGenerator, or other tools. Configs are organized by application, never by
delivery tool.

Architecture decisions are recorded in `docs/adr/`. Consult them before proposing
structural changes to the repo.

---

## Details

### Repo Structure

The layout is informed by the Red Hat Community of Practice reference,
[redhat-cop/gitops-standards-repo-template](https://github.com/redhat-cop/gitops-standards-repo-template),
and extends it with multi-tool delivery, ApplicationSet-driven app-of-apps,
team/AppProject governance, and agentic flywheel capabilities. See ADR-0001 for
the detailed comparison.

- The top-level directory structure is strictly validated against OpenAPI/Swagger path
  schema conventions — no ad-hoc directories or file sprawl.
- `clusters/` contains per-cluster gate files that control which apps run on which
  cluster and carry any per-cluster Application overrides.
- `sources/` contains all Kubernetes manifests targeted at Argo CD `spec.source`
  definitions. Each `sources/<app-name>` subdirectory is the stable unit of
  configuration for one application.
- `profiles/` contains organizational profiles: team configs, cluster-type app
  compositions, and data-center-specific overrides. Profiles are Argo CD Applications
  with organizational significance.
- `docs/` holds extended documentation including ADRs (`docs/adr/`).
- `schema/` holds non-renderable validation inputs (e.g., LDAP group allow-lists).
  Not tracked in git until schema enforcement is implemented.
- `README.md` and standard git files live at the root.

### App-of-Apps Pattern

- A single ApplicationSet generates all Argo CD Applications via a matrix generator:
  a list of cluster names × git-scanned `clusters/<clusterName>/*.yaml` files.
- The presence of `clusters/<clusterName>/<app>.yaml` deploys `sources/<app>` to
  that cluster. An empty file (`{}`) uses all org defaults. Any Argo CD Application
  field may be overridden in the file via `templatePatch`.
- Per ADR-0003, org defaults are declared once in the ApplicationSet template.
  Gate files contain only intentional deviations.
- The ApplicationSet implementation lives in `sources/app-of-apps`.

### Application Naming

All generated Application names follow a single pattern:

  `<clusterName>---<projectName>---<appName>`

`clusterName` is the Argo CD cluster secret / RHACM ManagedCluster name.
`projectName` is the Argo CD AppProject — the authorization boundary. Multiple
teams may hold roles within a single AppProject; team ownership does not affect
Application naming. Cluster context is exposed via labels and annotations on every
Application object regardless of deployment model.

### AppProjects and Teams

- Every generated Application must belong to an Argo CD AppProject.
- Every AppProject must be owned by one or more teams.
- Teams are sourced from LDAP Groups, which define Kubernetes Groups.
- Each team has three roles — admins, developers, viewers — mapping to OpenShift
  `admin`, `edit`, `view` namespace roles respectively.
- These roles are reflected into AppProject `roles` permissions.
- One team may own multiple AppProjects; one AppProject may be shared by multiple teams.

### Clusters

- Cluster names follow the pattern `<dc>-<type>-<env>-<n>`, e.g. `rdu-sno-dev-1`.
  See ADR-0007. Lab/personal clusters may use free-form names (e.g., `k8s-sno`).
- Each cluster has exactly one cluster-type. A cluster-type is a profile that
  declares the canonical set of apps for that class of cluster, composed from
  one or more app-groups.
- App-groups are reusable collections of apps that a cluster-type profile pulls
  in. A single cluster-type may include multiple app-groups (e.g., `hub` cluster-type
  includes `platform-base` + `hub-networking` app-groups).
- Data-center, cluster-type, and environment classifications are also reflected
  as RHACM `ManagedCluster` labels for policy placement rules.

### Platform Teams

- Platform teams are structurally identical to app teams.
- They additionally hold `cluster-admin` permissions on their clusters via the same
  team RBAC mechanism.
- All platform configurations are Argo CD Applications generated by the same
  app-of-apps ApplicationSet.

### Source Delivery

Kubernetes configurations in `sources/` are organized by **application**, never by
delivery tool. A given `sources/<app>` directory must be consumable by Argo CD (plain
manifests, Kustomize, or Helm), but the same source may also be delivered via Ansible
playbooks, RHACM Governance PolicyGenerators, or other mechanisms.

The primary driver is **bootstrapping**: before Argo CD is running on a cluster,
something else (Ansible, RHACM, a pipeline) must deliver the initial platform
configuration. Those tools read the same `sources/<app>` content — there is no
separate bootstrap copy of the config. A secondary benefit is that organizations can
migrate or switch delivery tools, or grow from per-cluster to hub-based Argo CD,
without reorganizing the repo. See `docs/adr/0001-sources-by-app.md`.

### Content Generation

- All generated content follows AI-considered guidelines.
- Prefer consistency and derivability from structure over explicit configuration.
- This `CLAUDE.md` is the source of truth for AI-assisted generation. Project
  instructions in Cowork/Claude settings defer to this file.

### Tooling Conventions

- **Use `oc` instead of `kubectl`** for all cluster interactions. This is an
  OpenShift environment; `oc` is the correct CLI and provides additional
  OpenShift-aware output and commands.
- **Operator subscriptions**: `startingCSV` should be omitted in `sources/`
  (org default) so dev clusters always get the current channel version.
  Production clusters pin via a gate file override or cluster kustomize patch —
  explicit, auditable, never automatic. See ADR-0003 cascade model.
