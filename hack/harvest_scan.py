#!/usr/bin/env python3
"""
config-harvester — Phase 0 prototype scanner (ADR-0011).

Read-only. Scans a live cluster via `oc`, applies the heuristic filter from
ADR-0011 to separate human-intended custom config from operator-generated and
defaulted state, neats survivors into re-appliable manifests, and prints a
report of what it WOULD capture. Writes nothing to the cluster and nothing to
git — this is the validation step that gates everything downstream.

Usage:
    ./harvest_scan.py                 # report only
    ./harvest_scan.py --emit ./out    # also write neated manifests to ./out
    ./harvest_scan.py --show-skips     # explain why things were skipped

Requires: oc (logged in), python3.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone

# --- Heuristic configuration (ADR-0011 — would live in config.yaml on the operator) ---

# Cluster-scoped, user-tunable singleton config. Always considered, regardless of
# namespace/owner heuristics, because these are the highest-value config and are
# known by kind. "Resource" here is the `oc get` plural/name form.
CURATED_CLUSTER_KINDS = [
    # config.openshift.io group — cluster config singletons
    "ingresses.config.openshift.io",
    "oauths.config.openshift.io",
    "images.config.openshift.io",
    "schedulers.config.openshift.io",
    "networks.config.openshift.io",
    "apiservers.config.openshift.io",
    "proxies.config.openshift.io",
    "consoles.config.openshift.io",
    "authentications.config.openshift.io",
    "featuregates.config.openshift.io",
    "infrastructures.config.openshift.io",
    "dnses.config.openshift.io",
    # machine / node tuning
    "machineconfigs.machineconfiguration.openshift.io",
    "kubeletconfigs.machineconfiguration.openshift.io",
    "containerruntimeconfigs.machineconfiguration.openshift.io",
    "tuneds.tuned.openshift.io",
    # console customization
    "consolelinks.console.openshift.io",
    "consolenotifications.console.openshift.io",
    "consoleyamlsamples.console.openshift.io",
]

# Always-include named singletons that live in an otherwise-denied namespace and
# carry no human field-manager, but are high-value config/provenance known by name.
# These bypass the namespace deny-list and the managedFields gate (like the cluster
# singletons in CURATED_CLUSTER_KINDS). The value is the repo-relative placement
# template ({cluster} is substituted at emit). Note these are deliberately placed
# OUTSIDE sources/ — they are captured provenance, NOT Argo-CD-reconciled apps.
CURATED_NAMED_OBJECTS = {
    # The installer's stored install-config: cluster identity/provenance
    # (baseDomain, networking, platform, topology). pullSecret is installer-blanked;
    # sshKey is a public key. Cluster-specific and NOT reconciled — it documents how
    # the cluster was installed, so it lands per-cluster, not in a shared app. A
    # future cluster-install/bootstrap app may later adopt it.
    ("kube-system", "cluster-config-v1"): "clusters/{cluster}/cluster-config",
}

# Namespaced kinds worth scanning for human-applied config in allowed namespaces.
CURATED_NAMESPACED_KINDS = [
    "configmaps",
    "secrets",  # never emitted raw — reported only (ADR-0011 constraint 5)
    "roles.rbac.authorization.k8s.io",
    "rolebindings.rbac.authorization.k8s.io",
    "resourcequotas",
    "limitranges",
    "networkpolicies.networking.k8s.io",
]

# System namespaces are denied by default EXCEPT these, where real cluster config
# legitimately lives.
SYSTEM_NS_ALLOW = {
    "openshift-config",
    "openshift-config-managed",
    "openshift-monitoring",
    "openshift-ingress",
    "openshift-ingress-operator",
}

# A resource's spec-owning field manager must look human/client to pass the
# managedFields filter. Operator/controller managers are skipped.
HUMAN_MANAGERS = (
    "kubectl",
    "oc",
    "Mozilla",            # console (browser user-agent), historical
    "openshift-console",
    "kube",               # kubeadmin via console
)

# Objects the platform auto-propagates into every namespace. They carry no
# ownerReference and no operator field-manager, so they slip past the owner and
# managedFields filters — but they are pure boilerplate, never human intent.
PROPAGATED_NAMES = {
    "kube-root-ca.crt",
    "openshift-service-ca.crt",
    "odh-trusted-ca-bundle",
    "system:deployers",
    "system:image-builders",
    "system:image-pullers",
}
PROPAGATED_SUFFIXES = ("-trusted-ca-bundle",)

# Argo CD tracking — already in the flywheel, skip.
ARGO_KEYS = (
    "argocd.argoproj.io/tracking-id",
    "app.kubernetes.io/instance",
)

# Temporal confidence signal (ADR-0011 heuristic 6). ADVISORY ONLY — it ranks and
# annotates capture candidates, it never includes or excludes. Objects created
# within this window of the cluster-install epoch are treated as the "install
# cohort" (most likely platform boilerplate); objects created well after install,
# or carrying a human field-manager edit-time, score as more likely human intent.
INSTALL_COHORT_WINDOW_S = 6 * 3600  # bootstrap spans hours, not minutes

# Server-side cruft stripped during neating.
DROP_METADATA = [
    "managedFields", "resourceVersion", "uid", "creationTimestamp",
    "generation", "selfLink", "ownerReferences",
]
DROP_ANNOTATIONS = [
    "kubectl.kubernetes.io/last-applied-configuration",
    "kapp.k14s.io/original",
]


@dataclass
class ScanResult:
    captured: list = field(default_factory=list)
    skipped: Counter = field(default_factory=Counter)
    skip_detail: list = field(default_factory=list)
    secrets_found: list = field(default_factory=list)


def oc_json(args: list[str]) -> dict | None:
    """Run `oc get ... -o json`, tolerating missing resource types."""
    try:
        out = subprocess.run(
            ["oc", "get", *args, "-o", "json"],
            capture_output=True, text=True, timeout=60,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"  ! oc failed for {' '.join(args)}: {e}", file=sys.stderr)
        return None
    if out.returncode != 0:
        # resource type not served on this cluster, or no permission — skip quietly
        return None
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return None


def is_system_ns(ns: str) -> bool:
    return ns.startswith("openshift-") or ns.startswith("kube-") or ns in ("default",)


def spec_manager_is_human(obj: dict) -> bool | None:
    """Inspect managedFields to find who owns spec/data. Returns True/False, or
    None if undeterminable (treated as 'inconclusive')."""
    mfs = obj.get("metadata", {}).get("managedFields") or []
    owners = []
    for mf in mfs:
        fields = mf.get("fieldsV1", {}) or {}
        # crude: any manager that touched spec or data
        if any(k in json.dumps(fields) for k in ('"f:spec"', '"f:data"', '"f:stringData"')):
            owners.append(mf.get("manager", ""))
    if not owners:
        return None
    return any(any(h in m for h in HUMAN_MANAGERS) for m in owners)


def parse_ts(s: str | None) -> datetime | None:
    """Parse an RFC3339 Kubernetes timestamp (e.g. 2024-12-01T10:11:12Z)."""
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None


def install_epoch() -> datetime | None:
    """Best-effort cluster-install time t0, used as the reference for the install
    cohort. Day-1 config (MachineConfigs, config CRs) is written *during* bootstrap,
    before CVO reports completion — so anchor on the EARLIEST install signal, not
    completion, or those objects look (incorrectly) pre-install. Candidates:
    ClusterVersion's initial history startedTime, and the kube-system namespace
    creationTimestamp (one of the first objects created). Take the earliest."""
    candidates = []
    cv = oc_json(["clusterversion", "version"])
    if cv:
        hist = cv.get("status", {}).get("history", []) or []
        if hist:  # last entry is the oldest = initial install
            candidates.append(parse_ts(hist[-1].get("startedTime")
                                       or hist[-1].get("completionTime")))
        candidates.append(parse_ts(cv.get("metadata", {}).get("creationTimestamp")))
    ns = oc_json(["namespace", "kube-system"])
    if ns:
        candidates.append(parse_ts(ns.get("metadata", {}).get("creationTimestamp")))
    candidates = [c for c in candidates if c]
    return min(candidates) if candidates else None


def cluster_name(override: str | None = None, default: str = "unknown-cluster") -> str:
    """The repo's name for this cluster, for per-cluster placement. Best-effort:
    prefer an explicit override, else the install-config's metadata.name (the
    install-time cluster name) from cluster-config-v1. The repo's canonical name is
    the Argo/ManagedCluster name, which is not reliably derivable in-cluster — so the
    production controller should be told its cluster name, not guess it."""
    if override:
        return override
    cm = oc_json(["cm", "cluster-config-v1", "-n", "kube-system"])
    if cm:
        ic = cm.get("data", {}).get("install-config", "") or ""
        in_meta = False
        for line in ic.splitlines():
            if re.match(r"^metadata:\s*$", line):
                in_meta = True
                continue
            if in_meta:
                if re.match(r"^\S", line):  # dedented out of the metadata block
                    in_meta = False
                    continue
                m = re.match(r"\s+name:\s*(\S+)", line)
                if m:
                    return m.group(1)
    return default


def last_human_edit(obj: dict) -> datetime | None:
    """The most recent time a human field-manager touched spec/data, from
    managedFields. More directly tied to intent than creationTimestamp, and robust
    to operator delete/recreate."""
    mfs = obj.get("metadata", {}).get("managedFields") or []
    times = []
    for mf in mfs:
        mgr = mf.get("manager", "")
        if not any(h in mgr for h in HUMAN_MANAGERS):
            continue
        fields = mf.get("fieldsV1", {}) or {}
        if any(k in json.dumps(fields) for k in ('"f:spec"', '"f:data"', '"f:stringData"')):
            t = parse_ts(mf.get("time"))
            if t:
                times.append(t)
    return max(times) if times else None


@dataclass
class Temporal:
    created: datetime | None = None
    delta_install_s: float | None = None  # created - t0 (seconds); None if t0 unknown
    install_cohort: bool = False          # born within the install window
    human_edit: datetime | None = None    # last human spec/data edit (managedFields)
    confidence: str = "unknown"           # human-likelihood: high | medium | low | unknown

    def annotate(self) -> str:
        bits = []
        if self.human_edit:
            bits.append(f"human-edit {self.human_edit:%Y-%m-%d}")
        if self.delta_install_s is not None:
            days = self.delta_install_s / 86400
            if self.install_cohort:
                bits.append("install-cohort")
            elif days >= 0:
                bits.append(f"+{days:.0f}d after install")
            else:
                bits.append(f"{abs(days):.0f}d before install (check t0)")
        return f"[{self.confidence}] " + ", ".join(bits) if bits else f"[{self.confidence}]"


def temporal_signal(obj: dict, epoch: datetime | None) -> Temporal:
    """Compute the advisory temporal confidence for an object. Never gates."""
    t = Temporal()
    t.created = parse_ts(obj.get("metadata", {}).get("creationTimestamp"))
    t.human_edit = last_human_edit(obj)
    if epoch and t.created:
        t.delta_install_s = (t.created - epoch).total_seconds()
        t.install_cohort = abs(t.delta_install_s) <= INSTALL_COHORT_WINDOW_S
    # Ranking, highest human-likelihood first. A demonstrated human edit-time is the
    # strongest signal; being born well after install is a softer boost; being born
    # in the install window is a soft (NOT disqualifying) demotion — day-1 human
    # config also lands there, so it never excludes.
    if t.human_edit is not None:
        t.confidence = "high"
    elif t.delta_install_s is not None and not t.install_cohort:
        t.confidence = "medium"
    elif t.install_cohort:
        t.confidence = "low"
    else:
        t.confidence = "unknown"
    return t


def is_argo_managed(obj: dict) -> bool:
    meta = obj.get("metadata", {})
    labels = meta.get("labels", {}) or {}
    annos = meta.get("annotations", {}) or {}
    return any(k in labels or k in annos for k in ARGO_KEYS)


def neat(obj: dict) -> dict:
    obj = json.loads(json.dumps(obj))  # deep copy
    obj.pop("status", None)
    meta = obj.get("metadata", {})
    for k in DROP_METADATA:
        meta.pop(k, None)
    annos = meta.get("annotations", {})
    for k in DROP_ANNOTATIONS:
        annos.pop(k, None)
    # drop operator-injected revision annotations
    for k in list(annos):
        if k.startswith(("kubectl.kubernetes.io/", "deployment.kubernetes.io/")):
            annos.pop(k, None)
    if not annos:
        meta.pop("annotations", None)
    return obj


def consider(obj: dict, kind: str, res: ScanResult, namespaced: bool,
             epoch: datetime | None = None) -> None:
    meta = obj.get("metadata", {})
    name = meta.get("name", "?")
    ns = meta.get("namespace", "")
    ref = f"{kind}/{name}" + (f" -n {ns}" if ns else "")

    if meta.get("ownerReferences"):
        res.skipped["owned (ownerReferences)"] += 1
        res.skip_detail.append((ref, "owned by a controller"))
        return

    if is_argo_managed(obj):
        res.skipped["already in flywheel (argo-managed)"] += 1
        res.skip_detail.append((ref, "already Argo-managed"))
        return

    if name in PROPAGATED_NAMES or name.endswith(PROPAGATED_SUFFIXES):
        res.skipped["auto-propagated boilerplate"] += 1
        res.skip_detail.append((ref, "platform-propagated into every namespace"))
        return

    # Curated named singletons are always-include: they bypass the namespace deny
    # and the managedFields gate, like the cluster-scoped singletons. (owner/argo/
    # propagated checks above still apply — a curated object that became owned or
    # Argo-managed is correctly skipped.)
    curated = (ns, name) in CURATED_NAMED_OBJECTS

    if not curated and namespaced and is_system_ns(ns) and ns not in SYSTEM_NS_ALLOW:
        res.skipped["system namespace (denied)"] += 1
        res.skip_detail.append((ref, f"system namespace {ns} not in allow-list"))
        return

    # managedFields heuristic gates ALL namespaced kinds (the cluster singletons in
    # CURATED_CLUSTER_KINDS are kept regardless — they are user-tunable by definition).
    # In an allow-listed SYSTEM namespace the bar is higher: a human manager must be
    # PROVEN, so inconclusive (server-created, no managedFields touching data) is
    # skipped. In a user namespace, inconclusive is given the benefit of the doubt.
    if namespaced and not curated:
        human = spec_manager_is_human(obj)
        if human is False:
            res.skipped["operator-owned fields"] += 1
            res.skip_detail.append((ref, "spec/data owned by operator manager"))
            return
        if human is None and is_system_ns(ns):
            res.skipped["unproven human (system ns)"] += 1
            res.skip_detail.append((ref, "no human field-manager in system ns"))
            return

    if kind == "secrets":
        # never emit raw; report only
        if obj.get("type") in ("kubernetes.io/service-account-token",
                                "kubernetes.io/dockercfg",
                                "helm.sh/release.v1"):
            res.skipped["generated secret"] += 1
            return
        res.secrets_found.append(ref)
        return

    res.captured.append((ref, neat(obj), temporal_signal(obj, epoch)))


def scan(emit: str | None, show_skips: bool, cluster: str | None = None) -> ScanResult:
    res = ScanResult()

    epoch = install_epoch()
    if epoch:
        print(f">> cluster install epoch (t0): {epoch:%Y-%m-%d %H:%M}Z")
    else:
        print(">> cluster install epoch unknown — temporal signal degrades to "
              "edit-time only")

    print(">> curated cluster-scoped config")
    for kind in CURATED_CLUSTER_KINDS:
        data = oc_json([kind])
        if not data:
            continue
        for obj in data.get("items", []):
            consider(obj, kind, res, namespaced=False, epoch=epoch)

    print(">> namespaced config (user + allow-listed system namespaces)")
    for kind in CURATED_NAMESPACED_KINDS:
        data = oc_json([kind, "--all-namespaces"])
        if not data:
            continue
        for obj in data.get("items", []):
            consider(obj, kind, res, namespaced=True, epoch=epoch)

    if emit:
        cname = cluster_name(cluster)
        for ref, obj, _ in res.captured:
            kind = obj.get("kind", "obj").lower()
            name = obj.get("metadata", {}).get("name", "x")
            ns = obj.get("metadata", {}).get("namespace", "")
            # Curated named objects use their repo-relative placement template
            # (e.g. clusters/<cluster>/cluster-config — provenance, NOT Argo-managed).
            # Everything else is an Argo source: sources/<app> (app = namespace, or
            # "cluster" for cluster-scoped objects).
            placement = CURATED_NAMED_OBJECTS.get((ns, name))
            rel = (placement.format(cluster=cname) if placement
                   else os.path.join("sources", ns or "cluster"))
            d = os.path.join(emit, rel)
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, f"{kind}-{name}.json"), "w") as f:
                json.dump(obj, f, indent=2)

    return res


def report(res: ScanResult, show_skips: bool) -> None:
    print("\n" + "=" * 64)
    print(f"CAPTURE CANDIDATES: {len(res.captured)}")
    print("=" * 64)
    # Sort by human-likelihood (high → low), then name. Advisory ordering only —
    # every candidate is still captured; the signal ranks reviewer attention.
    rank = {"high": 0, "medium": 1, "unknown": 2, "low": 3}
    by_conf = Counter(t.confidence for _, _, t in res.captured)
    for ref, _, t in sorted(res.captured, key=lambda c: (rank.get(c[2].confidence, 9), c[0])):
        print(f"  + {ref}  {t.annotate()}")
    print("\n  human-likelihood (advisory): " +
          ", ".join(f"{k}={by_conf.get(k, 0)}"
                    for k in ("high", "medium", "low", "unknown")))

    if res.secrets_found:
        print(f"\nSECRETS FOUND (excluded — seal via sources/sealed-secrets): "
              f"{len(res.secrets_found)}")
        for ref in sorted(res.secrets_found):
            print(f"  ~ {ref}")

    print(f"\nSKIPPED: {sum(res.skipped.values())}")
    for reason, n in res.skipped.most_common():
        print(f"  - {n:4d}  {reason}")

    if show_skips:
        print("\n  skip detail:")
        for ref, why in res.skip_detail[:200]:
            print(f"    - {ref}: {why}")

    total = len(res.captured) + len(res.secrets_found) + sum(res.skipped.values())
    signal = len(res.captured) / total * 100 if total else 0
    print(f"\nsignal ratio: {len(res.captured)}/{total} = {signal:.1f}% captured")
    print("(low % is expected & healthy — most cluster state is operator-owned)")


def main() -> int:
    ap = argparse.ArgumentParser(description="config-harvester Phase 0 scanner")
    ap.add_argument("--emit", metavar="DIR", help="write neated manifests here")
    ap.add_argument("--show-skips", action="store_true", help="explain skips")
    ap.add_argument("--cluster", metavar="NAME",
                    help="repo cluster name for per-cluster placement "
                         "(default: derived from install-config)")
    args = ap.parse_args()

    who = subprocess.run(["oc", "whoami"], capture_output=True, text=True)
    if who.returncode != 0:
        print("not logged in to a cluster (oc whoami failed)", file=sys.stderr)
        return 1
    print(f"scanning as {who.stdout.strip()} (read-only)\n")

    res = scan(args.emit, args.show_skips, args.cluster)
    report(res, args.show_skips)
    if args.emit:
        print(f"\nneated manifests written to {args.emit}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
