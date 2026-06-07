# profiles/cluster-types/app-groups/

Reusable app-group definitions. An app-group is a named, independently deployable
collection of apps that cluster-type profiles pull in by reference.

App-groups are the composable building blocks of cluster-types. The same app-group
can appear in multiple cluster-types without duplication.

## Example composition

```
hub cluster-type
  └── platform-base app-group   (every cluster)
  └── hub-networking app-group  (hub-specific)
  └── hub-primary app-group     (primary hub only)
```

A "primary hub" and "secondary hub" are the same `hub` cluster-type with different
app-group inclusions — not separate cluster-types.
