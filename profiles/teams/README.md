# profiles/teams/

Per-team configuration profiles.

Each subdirectory `profiles/teams/<team>/` is the single place for a team to
own their organizational configuration. Typically includes:

- `appproject.yaml` — Helm values file for `sources/app-projects/` defining
  the team's AppProject (RBAC roles, allowed repos, destinations).
- Any team-specific app sources or overrides.

## Adding a team

1. Create `profiles/teams/<team>/appproject.yaml` with the team's AppProject values.
2. Add `- <team>.yaml` (or the relative path) to the `valueFiles` list in
   `clusters/<cluster>/app-projects.yaml`.
3. Add team LDAP groups to `schema/ldap-groups.yaml` (once schema enforcement
   is active).

AppProjects owned by multiple teams list all teams in the `teams:` array of the
values file. The AppProject itself is associated with a primary team's directory
by convention, with other teams listed within it.

## Contents

- [`platform/`](platform/) — Platform team AppProject and configs
