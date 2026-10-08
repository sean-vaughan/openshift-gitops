# clusters/k8s-sno

Lab / development Single Node OpenShift cluster.

Free-form name (lab cluster, per ADR-0007). Future production clusters use the
`<dc>-<type>-<env>-<n>` pattern.

## Bootstrap

```bash
kubectl apply -k clusters/k8s-sno/app-of-apps/
```

## Apps deployed to this cluster

| Gate file | Source | Notes |
|---|---|---|
| [`app-of-apps.yaml`](app-of-apps.yaml) | `clusters/k8s-sno/app-of-apps/` | Self-managing ApplicationSet |
| [`app-projects.yaml`](app-projects.yaml) | `sources/app-projects/` | AppProject definitions |

## Personal-account repository cutover

The canonical repository is `dharmabruce/openshift-gitops`, reached by native
transfer of the original repository (ID `1258807777`) with its pull requests and
Git history intact. `openshift-gitops-pretransfer-archive` preserves the earlier
destination fork; it is not the deployment source. Do not deploy this change
until ownership and the original repository ID have been verified.

Follow ADR-0005 (self-management), ADR-0006 (promotion), ADR-0008 (PR flow), and
ADR-0009 (CI). The proposed ADR-0012 governance guidance classifies changes to
`sources/app-of-apps/` and `sources/app-projects/` for human approval. Obtain
approval of the concrete PR before merge or live cutover. The shared defaults
also apply to other consumers; this runbook authorizes live changes only on
`k8s-sno`.

1. Record the deployed commit and export the affected ApplicationSet,
   Applications, and AppProjects to a private local rollback directory. Record
   existing sync, health, source revisions, and sync policies. Do not export
   cluster Secrets. Confirm the endpoint is the existing personal `k8s-sno`
   context and compare live state against the exact reviewed commit.
2. Open a feature-branch PR after the native repository transfer is verified.
   Require all eight CI jobs to pass, and record supportability, security, and
   outcome review. Merge only after human approval. Record the merged commit
   SHA; do not substitute a moving `HEAD` for this validation reference.
3. Inspect every live AppProject used by the affected Applications. Ensure both
   the new canonical URL and the old transfer-redirect URL are permitted before
   changing any Application source. Promote the reviewed AppProject values first
   and confirm reconciliation; keep the existing blog-repository allowlist entry.
4. Move the `app-projects` Application to the canonical URL, preserving its
   revision, path, Helm values, destination, and sync policy. Reconcile it and
   verify its applied commit and both allowed URLs before proceeding.
5. Move `app-of-apps` to the canonical URL and deliberately sync its reviewed
   configuration. Preserve `prune: false` and `selfHeal: false` throughout, and
   inspect the diff before sync. Confirm the ApplicationSet Git generator and
   template use the new URL and that generated Application names are unchanged.
6. Change only remaining live Application sources that point to the old GitOps
   repository. Preserve intentional branch, revision, path, and sync-policy
   overrides, including development work. Leave the personal blog and any other
   separately sourced Applications unchanged. `ignoreApplicationDifferences`
   includes `.spec.source.repoURL`, so the template change alone does not move
   existing Applications; explicit, reviewed bootstrap intervention is required.
7. Verify every affected ApplicationSet, Application, and AppProject against the
   merged commit. Check reconciliation conditions, revisions, source URLs, and
   workload health against the recorded baseline. Report pre-existing failures
   separately; do not repair unrelated workloads or storage during this cutover.

For rollback, use the recorded per-Application source URL/revision/path and the
reviewed pre-cutover configuration. The original GitOps `main` baseline at
preparation time is `755544fa3fd601dcac76f623919d19aa5e50ba40`; confirm the live
baseline before relying on it. Restore the ApplicationSet deliberately and keep
self-management prune/self-heal disabled. Retain both AppProject URLs until all
affected Applications have reconciled and rollback is no longer needed. Removing
the old allowlist entry is a separate reviewed change.
