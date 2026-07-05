# etcd-defrag

Scheduled, conditional etcd defragmentation for **single-node OpenShift (SNO)**.

## Why this exists

etcd is a copy-on-write MVCC store: compaction frees old revisions *logically*
but never shrinks the database file. The gap between `dbSizeInUse` (live data)
and `dbSize` (allocated on disk) is fragmentation. Only `etcdctl defrag`
reclaims it, and it fires the `etcdDatabaseHighFragmentationRatio` alert once
in-use drops below 50% of allocated (with a 100 MiB floor).

On multi-node clusters the cluster-etcd-operator's `DefragController`
defragments members automatically, one at a time, while the others hold quorum.
On SNO there is only one etcd member, so defrag briefly blocks the whole control
plane — the operator therefore **disables** its DefragController on
`SingleReplica` topology (`DefragControllerDisabled=True (AsExpected)`) and
leaves defrag to the admin. This CronJob is that admin, automated.

## Behaviour

A weekly (Sun 03:00) CronJob that is **conditional**: it reads
`dbSize`/`dbSizeInUse` from `etcdctl endpoint status` and only defragments when
the DB is `>100 MiB` **and** `>=45%` fragmented — the same thresholds the
operator's DefragController uses. On most runs it is a no-op; it only incurs the
brief control-plane pause when there is genuine slack to reclaim. It clears a
`NOSPACE` alarm afterward if defrag trips one.

It reuses the etcd pod's own `etcdctl` container (certs and endpoints already
wired), so there are no etcd client certificates to mount or rotate. RBAC is a
namespaced Role in `openshift-etcd` granting only `get/list pods` and
`create pods/exec`.

## Scope

Intended for SNO / `SingleReplica` clusters only. On multi-node clusters the
operator already handles this — do not deploy there. Deployed to k8s-sno via
`clusters/k8s-sno/etcd-defrag.yaml`.
