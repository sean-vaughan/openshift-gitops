# profiles/cluster-types/

Cluster-type profiles. Each subdirectory defines the canonical application
composition for one class of cluster.

A cluster-type profile is an Argo CD Application (or set of gate files) that
deploys the right app-groups for its cluster class. Every cluster has exactly one
cluster-type. The cluster-type is part of the cluster name (`<dc>-<type>-<env>-<n>`,
per ADR-0007).

## App-groups

App-groups live under [`app-groups/`](app-groups/) and are reusable, composable
collections of apps. A cluster-type is defined by which app-groups it includes.

```
cluster-types/
  sno/          Single Node OpenShift — lightweight, all-in-one
  hub/          Hub cluster — manages other clusters via RHACM
  app/          General-purpose application cluster
  app-groups/
    platform-base/    Core platform apps every cluster gets
    hub-networking/   Networking apps specific to hub clusters
    observability/    Monitoring and logging stack
```

## Defining a new cluster-type

1. Create `profiles/cluster-types/<type>/` with a README and an app composition
   definition (gate files or an ApplicationSet overlay).
2. Add the cluster-type code to the taxonomy in ADR-0007.
3. Document which app-groups the cluster-type includes.
