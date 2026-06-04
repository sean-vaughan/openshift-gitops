# ADR-0001: Organize sources by application, not delivery tool

- **Status**: Accepted
- **Date**: 2026-06-03

## Context

Kubernetes configurations can be organized in multiple ways. One natural approach is
to group them by the tool that delivers them — an `argo/` directory for Argo CD
manifests, an `ansible/` directory for Ansible-delivered configs, an `rhacm/`
directory for RHACM PolicyGenerator inputs, and so on.

This repo needs to support multiple delivery mechanisms for two reasons:

1. **Bootstrapping**: Before Argo CD is running on a cluster, something else — Ansible,
   RHACM, a pipeline — must deliver the initial platform configuration. If configs are
   organized by tool, bootstrapping requires a separate copy or a different path for the
   same logical application.

2. **Migration and flexibility**: Organizations grow. A team may start with per-cluster
   Argo CD instances and later consolidate onto a hub. Or they may shift certain apps
   from Argo CD reconciliation to RHACM governance. Organizing by tool makes these
   transitions require wholesale repo restructuring.

## Decision

Organize `sources/` by **application name**, never by delivery tool.

Each `sources/<app-name>` directory represents a logical application and is the stable
unit of configuration. The same directory is the source for any tool that needs to
deliver that application — Argo CD, Ansible, RHACM PolicyGenerator, or others.

A `sources/<app>` directory must be a valid Argo CD Application source (plain
manifests, Kustomize, or Helm), as Argo CD is the primary steady-state delivery
mechanism. Other tools consume the same path.

## Consequences

**Positive:**

- No separate bootstrap copy of configs. The same `sources/<app>` path is used at
  every lifecycle phase: initial provisioning, steady-state reconciliation, and
  promotion.
- Migrating from per-cluster Argo CD to hub-based Argo CD changes generator
  configuration, not directory structure.
- Switching an app from Argo CD delivery to RHACM governance (or back) requires no
  repo reorganization.
- The repo remains the single source of truth for what an application's configuration
  is, independent of how it is currently being delivered.
- Strict directory layout enables AI-assisted generation: tooling can derive Argo CD
  Application names, AppProject membership, and delivery config directly from the
  directory structure.

**Negative / constraints:**

- Every `sources/<app>` must be structured in a way that is valid for Argo CD (plain
  manifests, Kustomize, or Helm). This constrains the format of configs even when Argo
  CD is not the active delivery mechanism for that app.
- The delivery tool in use at any given lifecycle phase must be tracked elsewhere
  (labels, annotations, or external state) rather than being visible from the directory
  structure itself.

## Related

- `CLAUDE.md` — Source Delivery section
- ADR-0002 (planned): Application naming convention
