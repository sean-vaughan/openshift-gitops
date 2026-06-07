# Ownership Model

> **Zoom level:** Authorization — who owns what, AppProjects, RBAC.
> **Previous:** [← Configuration Cascade](04-configuration-cascade.md) | **Next:** [Bootstrap Sequence →](06-bootstrap.md)
> **ADR:** [ADR-0003](../adr/0003-organizational-defaults-over-boilerplate.md)

Every Argo CD Application belongs to an AppProject. Every AppProject is owned by
one or more teams. Teams source from LDAP groups and map to OpenShift RBAC roles.

```mermaid
%%{init: {'flowchart': {'curve': 'step', 'padding': 20}}}%%
flowchart TD
    classDef platform fill:#eceff1,stroke:#546e7a,color:#000
    classDef appteam  fill:#e8f5e9,stroke:#2e7d32,color:#000
    classDef argo     fill:#fff8e1,stroke:#e65100,color:#000
    classDef ldap     fill:#e8eaf6,stroke:#3949ab,color:#000
    classDef hub      fill:#ede7f6,stroke:#4527a0,color:#000

    subgraph LDAP["LDAP / Identity Provider"]
        GRP_PA["platform-admins"]:::ldap
        GRP_PD["platform-developers"]:::ldap
        GRP_PV["platform-viewers"]:::ldap
        GRP_AA["app-team-admins"]:::ldap
        GRP_AD["app-team-developers"]:::ldap
        GRP_AV["app-team-viewers"]:::ldap
    end

    subgraph PROJ_P["«AppProject» platform"]
        ROLE_PA["role: platform-admins\npolicies: applications, *, platform/*"]:::platform
        ROLE_PD["role: platform-developers\npolicies: get + sync + override, platform/*"]:::platform
        ROLE_PV["role: platform-viewers\npolicies: get, platform/*"]:::platform
    end

    subgraph PROJ_A["«AppProject» app-team"]
        ROLE_AA["role: app-team-admins\npolicies: applications, *, app-team/*"]:::appteam
        ROLE_AD["role: app-team-developers\npolicies: get + sync + override, app-team/*"]:::appteam
        ROLE_AV["role: app-team-viewers\npolicies: get, app-team/*"]:::appteam
    end

    APPS_P["«argo-apps»\nk8s-sno---platform---*"]:::platform
    APPS_A["«argo-apps»\nk8s-sno---app-team---*"]:::appteam

    GRP_PA --> ROLE_PA
    GRP_PD --> ROLE_PD
    GRP_PV --> ROLE_PV
    GRP_AA --> ROLE_AA
    GRP_AD --> ROLE_AD
    GRP_AV --> ROLE_AV

    PROJ_P -->|"governs"| APPS_P
    PROJ_A -->|"governs"| APPS_A

    ROLE_PA -->|"OpenShift\nadmin role"| NS_P["platform namespaces"]:::platform
    ROLE_AA -->|"OpenShift\nadmin role"| NS_A["app-team namespaces"]:::appteam
```

## AppProject source: profiles/teams/

Each team's AppProject is defined as a Helm values file consumed by `sources/app-projects/chart/`.
The chart encodes the RBAC template (3 roles per team); the values file provides
only team-specific data.

```mermaid
%%{init: {'flowchart': {'curve': 'step', 'padding': 20}}}%%
flowchart LR
    classDef git      fill:#e3f2fd,stroke:#1565c0,color:#000
    classDef argo     fill:#fff8e1,stroke:#e65100,color:#000
    classDef platform fill:#eceff1,stroke:#546e7a,color:#000
    classDef appteam  fill:#e8f5e9,stroke:#2e7d32,color:#000

    CHART["sources/app-projects/chart/\n«Helm chart»\n\ntemplate: AppProject\nwith 3 roles per team\n(RBAC org default)"]:::argo

    VALUES_P["sources/app-projects/\nplatform.yaml\n\nprojects:\n  - name: platform\n    teams:\n      - name: platform\n        adminsGroup: platform-admins\n        …"]:::platform

    VALUES_A["sources/app-projects/\napp-team.yaml\n\nprojects:\n  - name: app-team\n    teams:\n      - name: app-team\n        destinations:\n          - namespace: app-team-*\n        clusterResourceWhitelist: []"]:::appteam

    PROJ_P_OUT["«AppProject»\nplatform"]:::platform
    PROJ_A_OUT["«AppProject»\napp-team"]:::appteam

    CHART    -->|helm template| PROJ_P_OUT
    CHART    -->|helm template| PROJ_A_OUT
    VALUES_P -->|values| PROJ_P_OUT
    VALUES_A -->|values| PROJ_A_OUT
```

## Shared AppProjects (multi-team ownership)

An AppProject may be co-owned by listing multiple teams in the `teams:` array.
The chart generates one set of roles per team entry. Shared projects are defined
in the primary owning team's profile directory by convention.

```yaml
# profiles/teams/platform/shared-infra-appproject.yaml
projects:
  - name: shared-infra
    description: "Shared infrastructure — jointly owned by platform and network teams"
    teams:
      - name: platform
        adminsGroup: platform-admins
        developersGroup: platform-developers
        viewersGroup: platform-viewers
      - name: network
        adminsGroup: network-admins
        developersGroup: network-developers
        viewersGroup: network-viewers
```
