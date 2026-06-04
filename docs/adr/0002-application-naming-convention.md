# ADR-0002: Application naming convention

- **Status**: Accepted
- **Date**: 2026-06-03

## Context

Argo CD Application objects are namespaced Kubernetes resources. Their `metadata.name`
must be unique within the Argo CD namespace where they are created.

When a single central (hub) Argo CD instance manages applications across multiple
destination clusters, the same logical application — e.g., `rbac` in project
`platform` — may exist on many clusters simultaneously. All of those Application
objects live in the same Argo CD namespace on the hub, so the cluster must be part of
the name to preserve uniqueness.

When each cluster runs its own Argo CD instance, Application objects for different
clusters live in different namespaces by definition. The cluster name is already
implied by the local Argo CD instance and does not need to appear in the Application
name.

A naive approach would use the team name as the ownership identifier in
Application names. However, multiple teams may own a single AppProject, and team
membership changes over time. Encoding team identity in the Application name would
cause names to change when ownership changes. AppProject is the correct unit because
it is the stable Argo CD authorization boundary: an Application always belongs to
exactly one AppProject, and that relationship does not change when team membership
evolves. If need be, AppProject name may be the same as team name if there is a
one-to-one relationship between the two.

## Decision

Use the **shortest name that preserves uniqueness**, derived from the Argo CD
deployment model in use:

- **Hub Argo CD** (one instance managing multiple destination clusters):

  ```
  <clusterName>---<projectName>---<appName>
  ```

- **Per-cluster Argo CD** (each cluster runs its own instance):

  ```
  <projectName>---<appName>
  ```

`projectName` is the Argo CD AppProject name — the authorization boundary.
`appName` is the `sources/<app-name>` directory name.
`clusterName` is the RHACM ManagedCluster name, included only when required for
uniqueness.

Cluster context is always exposed via labels and annotations on the Application object,
regardless of whether it appears in the name:

```yaml
metadata:
  labels:
    gitops.openshift.io/cluster-name: <clusterName>
    gitops.openshift.io/project: <projectName>
    gitops.openshift.io/app-name: <appName>
    gitops.openshift.io/source-path: <appName>
```

The app-of-apps ApplicationSet generates names according to whichever pattern applies
to the deployment model of the organization. Both patterns are supported; the active
pattern is configured in `sources/app-of-apps`.

## Consequences

**Positive:**

- Names are as short as correctness allows — easier to read in the Argo CD UI and
  in `kubectl` output.
- Names are stable: team ownership changes do not rename Applications.
- The naming rule is mechanical and derivable from the directory structure, enabling
  automated generation and validation.
- Migrating from per-cluster Argo CD to hub-based Argo CD is a generator config
  change (adding `<clusterName>---` prefix), not a rename of every Application. The
  source paths and AppProject names are unchanged.
- Cluster context is always available via labels regardless of deployment model.

**Negative / constraints:**

- The deployment model (hub vs. per-cluster) must be declared in `sources/app-of-apps`
  configuration so the ApplicationSet generates the correct name pattern.
- Changing deployment models (e.g., migrating from per-cluster to hub) will rename
  all Application objects. This is expected and intentional — it reflects a real change
  in the uniqueness domain — but it requires Argo CD to re-adopt the Applications under
  new names.

## Related

- `CLAUDE.md` — Application Naming section
- ADR-0001: Organize sources by application, not delivery tool
