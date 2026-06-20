#!/usr/bin/env python3
"""
config-harvester — PR-authoring step (ADR-0011 "Output: pull request",
ADR-0012 authoring loop, ADR-0016 PR-composition rules, ADR-0017 reversibility).

This is the step AFTER hack/harvest_scan.py: the scanner has already decided
WHICH objects are candidate custom config and neated them into manifests. This
module composes the branch artifacts a reviewer (or, later, the in-cluster
controller's `gh`) turns into a PR:

  * a commit message,
  * a PR body (sensor signal, what was captured/skipped, reviewer checklist),
  * the governance-lane decision (auto-merge vs human-approval).

DESIGN DISCIPLINE (Engine Role Charter / ADR-0017 — grade contact, not narrative):

  1. The cheap local model only ever DRAFTS narrative (summary, commit/PR prose).
     It is fed an inventory the harvester ALREADY produced; it never authors
     manifest content — neating/field-policy in harvest_scan.py is the
     deterministic ground truth for intent-vs-incidental.
  2. The model NEVER decides the merge gate. The binding lane is computed
     deterministically from changed paths + cluster role + security-sensitive
     kinds (classify_lane, below). The model may only SUGGEST a lane, and that
     suggestion can make the result STRICTER, never looser — a confident cheap
     model as approver is the hazard we refuse.
  3. If the endpoint is unreachable, drafting degrades to a deterministic
     skeleton. The lane decision is unaffected (it never depended on the model).

Like harvest_scan.py this Phase-0 step writes NOTHING to git or the cluster — it
emits branch artifacts to a directory. Opening the PR with a PR-only token
(ADR-0011) is a later phase.

Usage:
    ./harvest_author.py --cluster k8s-sno --out ./branch   # scan + author
    ./harvest_author.py --self-test                         # offline invariants
    ./harvest_author.py --demo                              # synthetic inventory
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

# harvest_scan lives beside us; Python puts this script's dir on sys.path[0].
import harvest_scan  # noqa: E402
import inference  # noqa: E402


# --------------------------------------------------------------------------- #
# Captured-item model — the deterministic facts the lane decision reasons over.
# --------------------------------------------------------------------------- #

# Kinds that are security-sensitive by definition (ADR-0012 human-approval lane):
# RBAC, secret material, AppProject roles. A capture touching any of these can
# never auto-merge. Matched against the harvest_scan `oc get` resource spelling.
SECURITY_SENSITIVE_KINDS = (
    "roles.rbac.authorization.k8s.io",
    "rolebindings.rbac.authorization.k8s.io",
    "clusterroles.rbac.authorization.k8s.io",
    "clusterrolebindings.rbac.authorization.k8s.io",
    "secrets",
    "sealedsecrets.bitnami.com",
)

# Repo path prefixes that are security-sensitive or structural (ADR-0012).
SECURITY_SENSITIVE_PATHS = (
    "sources/sealed-secrets/",
    "sources/app-projects/",
)
STRUCTURAL_PATHS = (
    "sources/app-of-apps/",   # the ApplicationSet template
    "schema/",                # validation inputs
)


@dataclass
class Captured:
    """One emitted object the PR will contain. All fields are deterministic —
    derived from harvest_scan output, never from the model."""
    kind: str
    name: str
    namespace: str
    confidence: str          # advisory temporal signal (ADR-0011 heuristic 6)
    repo_path: str           # repo-relative path this object emits to
    obj: dict | None = None  # the neated manifest body (None in lane-only/demo)
    origin: str = "human-likely"  # "human-likely" | "operator-likely" (partitions PRs)

    @property
    def ref(self) -> str:
        return f"{self.kind}/{self.name}" + (f" -n {self.namespace}" if self.namespace else "")

    @property
    def security_sensitive(self) -> bool:
        return (self.kind in SECURITY_SENSITIVE_KINDS
                or self.repo_path.startswith(SECURITY_SENSITIVE_PATHS))


# --------------------------------------------------------------------------- #
# Cluster role — the reversibility classifier (ADR-0017): the load-bearing axis.
# --------------------------------------------------------------------------- #

# ADR-0007 cluster naming: <dc>-<type>-<env>-<n>. The env segment carries
# reversibility. Lab/personal clusters use free-form names. Conservative by
# construction (ADR-0012 constraint 6, ADR-0017 "unknown -> irreversible"):
# ONLY clusters we can positively read as dev/lab are reversible; everything
# else — test, staging, prod, or unparseable — is treated as irreversible.
DEV_ENV_TOKENS = {"dev", "lab", "sandbox", "sbx"}
PROD_ENV_TOKENS = {"prd", "prod", "production"}
# Free-form lab clusters that predate ADR-0007 naming and are known-reversible.
KNOWN_LAB_CLUSTERS = {"k8s-sno"}


def cluster_role(name: str | None) -> str:
    """Return 'dev' (reversible), 'prod' (irreversible), or 'unknown'
    (treated as irreversible). Never guesses optimistically."""
    if not name:
        return "unknown"
    if name in KNOWN_LAB_CLUSTERS:
        return "dev"
    parts = name.split("-")
    # <dc>-<type>-<env>-<n>: the env is the second-to-last segment.
    if len(parts) >= 4:
        env = parts[-2].lower()
        if env in DEV_ENV_TOKENS:
            return "dev"
        if env in PROD_ENV_TOKENS:
            return "prod"
    return "unknown"


# --------------------------------------------------------------------------- #
# Lane classifier — the binding gate. Deterministic; the model cannot reach it.
# --------------------------------------------------------------------------- #

AUTO_MERGE = "auto-merge"
HUMAN_APPROVAL = "human-approval"


@dataclass
class LaneDecision:
    lane: str
    reasons: list[str] = field(default_factory=list)

    @property
    def auto(self) -> bool:
        return self.lane == AUTO_MERGE


def _path_is_auto_mergeable(path: str, role: str) -> tuple[bool, str]:
    """Per-path allowlist (ADR-0012 auto-merge lane). Returns (ok, reason)."""
    if path.startswith(SECURITY_SENSITIVE_PATHS):
        return False, f"security-sensitive path ({path})"
    if path.startswith(STRUCTURAL_PATHS):
        return False, f"structural path ({path})"
    if path.startswith("docs/adr/"):
        return False, "ADR change — decisions are a human act (ADR-0012)"
    if path.endswith("/index.md") or path.startswith("docs/"):
        return True, ""  # OKF records + docs (except docs/adr, handled above)
    # cluster-config provenance (ADR-0011): install identity (baseDomain,
    # networking, topology). Not Argo-reconciled, but a human should eyeball it.
    if "/cluster-config/" in path:
        return False, f"cluster install provenance ({path}) — human review"
    if path.startswith("sources/"):
        if role != "dev":
            return False, f"source change resolves to {role} cluster, not dev/lab"
        return True, ""
    if path.startswith("clusters/"):
        # dev/lab gate files are auto-mergeable; provenance handled above.
        if role != "dev":
            return False, f"cluster gate file resolves to {role} cluster"
        return True, ""
    return False, f"unclassified path ({path}) — fail safe to human-approval"


def classify_lane(items: list[Captured], role: str, secrets_found: int) -> LaneDecision:
    """The binding governance lane (ADR-0012 #99-126, refined by ADR-0017 onto
    reversibility/blast-radius). auto-merge requires ALL of: every changed path
    on the allowlist, no security-sensitive kind, no excluded secrets needing a
    human to seal, and a dev/lab (reversible) target. Anything else -> human."""
    reasons: list[str] = []

    if role == "prod":
        return LaneDecision(HUMAN_APPROVAL, ["production cluster in scope (ADR-0012)"])
    if role == "unknown":
        reasons.append("cluster role unknown — treated as irreversible (ADR-0017)")

    for it in items:
        if it.security_sensitive:
            reasons.append(f"security-sensitive kind: {it.ref} (ADR-0012 constraint 8)")
        ok, why = _path_is_auto_mergeable(it.repo_path, role)
        if not ok:
            reasons.append(why)

    if secrets_found:
        reasons.append(f"{secrets_found} secret(s) found — manual sealing required "
                       f"(ADR-0011 constraint 5)")

    if role == "dev" and not reasons:
        return LaneDecision(AUTO_MERGE,
                            ["all paths on auto-merge allowlist; reversible dev/lab "
                             "target; no security-sensitive content (ADR-0012/0017)"])
    # Fail safe: any reason at all routes to human-approval (ADR-0012 constraint 6).
    return LaneDecision(HUMAN_APPROVAL, reasons or ["conservative default"])


# Lane strictness ordering — used to fold in the model's *advisory* suggestion.
_STRICTNESS = {AUTO_MERGE: 0, HUMAN_APPROVAL: 1}


def stricter(a: str, b: str) -> str:
    """The model may only tighten the gate, never loosen it."""
    if a not in _STRICTNESS:
        return HUMAN_APPROVAL
    if b not in _STRICTNESS:
        return a
    return a if _STRICTNESS[a] >= _STRICTNESS[b] else b


# --------------------------------------------------------------------------- #
# Model drafting — narrative ONLY, strict-JSON contract, degrades gracefully.
# --------------------------------------------------------------------------- #

DRAFT_SYSTEM = """\
You draft the human-facing narrative for a config-harvester pull request that has
ALREADY been fully composed by a deterministic tool. Hard rules:
- You do NOT author, edit, or invent any Kubernetes manifest content. The objects
  listed are already captured and neated. Describe them; never produce YAML.
- You do NOT decide whether this PR auto-merges. A deterministic policy owns that.
  You may only flag concerns that make a change MORE sensitive (push toward human
  review), never less.
- Be concrete and terse. A reviewer reads this to decide what to verify.
Return ONLY a JSON object with these string/array fields:
  "summary": one sentence, what this harvest captured.
  "commit_subject": <=70 chars, conventional-commit style, e.g.
     "chore(harvest): capture <n> objects from <cluster>".
  "commit_body": 2-4 lines of context for the commit.
  "pr_overview": 1-2 short paragraphs of markdown for the PR body.
  "reviewer_checklist": array of specific things the reviewer should verify.
  "supportability_flags": array of any captured object that looks like a
     hand-edited operator-managed / openshift-* surface (ADR-0012 support role);
     [] if none.
  "lane_concern": one of "none" or "wants-human-review", your advice only.
"""


def draft_with_model(cluster: str, role: str, items: list[Captured],
                     secrets_found: int, det_lane: LaneDecision) -> tuple[dict | None, dict | None]:
    """Ask the shared inference core to draft PR narrative. Returns (draft, meta)
    or (None, None) if the endpoint is unreachable — drafting is optional."""
    inventory = [
        {"ref": it.ref, "kind": it.kind, "path": it.repo_path,
         "confidence": it.confidence, "security_sensitive": it.security_sensitive}
        for it in items
    ]
    user = json.dumps({
        "cluster": cluster, "cluster_role": role,
        "deterministic_lane": det_lane.lane,
        "deterministic_lane_reasons": det_lane.reasons,
        "secrets_found_excluded": secrets_found,
        "captured": inventory,
    }, indent=2)
    try:
        content, meta = inference.chat(
            [{"role": "system", "content": DRAFT_SYSTEM},
             {"role": "user", "content": user}],
            json_object=True, temperature=0.2,
        )
    except inference.InferenceError as e:
        print(f"  ! inference unavailable, drafting deterministic skeleton: {e}",
              file=sys.stderr)
        return None, None
    try:
        return json.loads(content), meta
    except json.JSONDecodeError:
        print("  ! model returned non-JSON; using deterministic skeleton", file=sys.stderr)
        return None, None


# --------------------------------------------------------------------------- #
# Artifact composition — deterministic facts always; model prose when present.
# --------------------------------------------------------------------------- #

_CONF_RANK = {"high": 0, "medium": 1, "unknown": 2, "low": 3}


def _inventory_table(items: list[Captured]) -> str:
    if not items:
        return "_No objects captured._\n"
    rows = ["| Object | Path | Confidence | Security-sensitive |",
            "|---|---|---|---|"]
    # Most-human-likely first (ADR-0011 heuristic 6 ranks reviewer attention).
    for it in sorted(items, key=lambda i: (_CONF_RANK.get(i.confidence, 9), i.repo_path)):
        rows.append(f"| `{it.ref}` | `{it.repo_path}` | {it.confidence} | "
                    f"{'**yes**' if it.security_sensitive else 'no'} |")
    return "\n".join(rows) + "\n"


def compose(cluster: str, role: str, items: list[Captured], secrets: list[str],
            det_lane: LaneDecision, binding_lane: str, draft: dict | None,
            pr_kind: str = "high-signal") -> dict:
    """Returns {'commit_message', 'pr_body', 'lane'} — deterministic facts are
    authoritative; model prose is clearly bounded to the 'why' sections."""
    n = len(items)
    triage = pr_kind == "operator-triage"
    scope = "operator-triage" if triage else "harvest"
    subj = (draft or {}).get("commit_subject") \
        or f"chore({scope}): capture {n} object(s) from {cluster}"
    body = (draft or {}).get("commit_body") \
        or f"Config-harvester capture from cluster {cluster} ({role})."
    commit_message = f"{subj}\n\n{body}\n"

    overview = (draft or {}).get("pr_overview") \
        or (f"The config-harvester (ADR-0011) scanned `{cluster}` and proposes "
            f"capturing {n} object(s) into the flywheel.")
    checklist = (draft or {}).get("reviewer_checklist") or [
        "Confirm each captured object is intended human config, not operator state.",
        "Confirm no secret material is present in clear text.",
    ]
    flags = (draft or {}).get("supportability_flags") or []
    drafted_by = "shared inference core" if draft else "deterministic skeleton (no model)"

    title = ("Config-harvester — operator-triage" if triage
             else "Config-harvester capture")
    lines = [
        f"## {title} — `{cluster}`",
        "",
        f"**Sensor:** config-harvester (ADR-0011) &nbsp; **Cluster role:** "
        f"{role} &nbsp; **Drafted by:** {drafted_by}",
        "",
    ]
    if triage:
        lines += [
            "> ⚠️ **Likely operator/OLM/Helm-managed objects — triage, don't rubber-stamp.**",
            "> These were captured but flagged `operator-likely` (ADR-0011 rank-don't-drop):",
            "> `:`-in-name RBAC, operator labels, or a non-human field-manager. Most should",
            "> be skipped; keep only the ones you actually authored. The high-signal PR is",
            "> the one to focus on.",
            "",
        ]
    lines += [
        overview,
        "",
        "### Governance lane",
        "",
        f"**Binding lane: `{binding_lane}`** — decided deterministically "
        f"(ADR-0012 / ADR-0017), not by the model.",
        "",
    ]
    lines += [f"- {r}" for r in det_lane.reasons]
    if binding_lane != det_lane.lane:
        lines.append(f"- model advice tightened the lane to `{binding_lane}`")
    lines += ["", "### Captured objects", "", _inventory_table(items)]
    if secrets:
        lines += ["### Secrets found (excluded — seal via `sources/sealed-secrets/`)", ""]
        lines += [f"- `{s}`" for s in secrets] + [""]
    if flags:
        lines += ["### Supportability flags (ADR-0012 support role — advisory)", ""]
        lines += [f"- {f}" for f in flags] + [""]
    lines += ["### Reviewer checklist", ""]
    lines += [f"- [ ] {c}" for c in checklist]
    lines += ["", "---", "_Phase-0 artifact: no PR opened, no cluster or git writes "
              "(ADR-0011). Generated by `hack/harvest_author.py`._"]
    return {"commit_message": commit_message,
            "pr_body": "\n".join(lines) + "\n", "lane": binding_lane}


# --------------------------------------------------------------------------- #
# Manifest emit — YAML + kustomization.yaml per partition (ADR-0011 output).
# --------------------------------------------------------------------------- #

# Prefer PyYAML (correct + pretty; present in the in-cluster gitops-agent image).
# Absent (local dev / slim env), fall back to a minimal serializer that leans on
# JSON — a YAML *subset* — for every scalar and list, so output is correct by
# construction. We deliberately do NOT hand-roll block scalars (the foot-gun);
# multiline strings render JSON-escaped (valid, just less pretty than PyYAML).
try:
    import yaml as _yaml
    _HAVE_YAML = True
except ImportError:
    _HAVE_YAML = False

_YAML_RESERVED = {"true", "false", "null", "yes", "no", "on", "off", "none", "y", "n", "~"}
_PLAIN = re.compile(r"^[A-Za-z][\w./@-]*$")  # safe to emit unquoted


def _yaml_scalar(v) -> str:
    if v is True:
        return "true"
    if v is False:
        return "false"
    if v is None:
        return "null"
    if isinstance(v, (int, float)):
        return json.dumps(v)
    s = str(v)
    if _PLAIN.match(s) and s.lower() not in _YAML_RESERVED:
        return s
    return json.dumps(s, ensure_ascii=False)  # JSON string == valid YAML dq-scalar


def _minimal_yaml(data: dict, indent: int = 0) -> str:
    pad = "  " * indent
    lines = []
    for k, v in data.items():
        key = str(k) if _PLAIN.match(str(k)) else json.dumps(str(k))
        if isinstance(v, dict) and v:
            lines.append(f"{pad}{key}:")
            lines.append(_minimal_yaml(v, indent + 1))
        elif isinstance(v, dict):
            lines.append(f"{pad}{key}: {{}}")
        elif isinstance(v, list):
            lines.append(f"{pad}{key}: {json.dumps(v, ensure_ascii=False)}")  # flow = valid YAML
        else:
            lines.append(f"{pad}{key}: {_yaml_scalar(v)}")
    return "\n".join(lines)


def dump_manifest(obj: dict) -> str:
    if _HAVE_YAML:
        return _yaml.safe_dump(obj, default_flow_style=False, sort_keys=False)
    return _minimal_yaml(obj) + "\n"


def emit_manifests(branch_dir: str, items: list[Captured]) -> list[str]:
    """Write each captured object as a YAML manifest under branch_dir/<repo_path>,
    and a kustomization.yaml per sources/ directory. Provenance under clusters/ is
    NOT an Argo source (ADR-0011), so it gets no kustomization. Items without a
    body (demo/lane-only) are skipped. Returns the repo-relative paths written."""
    from collections import defaultdict
    src_dirs: dict[str, list[str]] = defaultdict(list)
    written = []
    for it in items:
        if it.obj is None:
            continue
        path = os.path.join(branch_dir, it.repo_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(dump_manifest(it.obj))
        written.append(it.repo_path)
        if it.repo_path.startswith("sources/"):
            src_dirs[os.path.dirname(it.repo_path)].append(os.path.basename(it.repo_path))
    for d, files in sorted(src_dirs.items()):
        kobj = {"apiVersion": "kustomize.config.k8s.io/v1beta1",
                "kind": "Kustomization", "resources": sorted(files)}
        with open(os.path.join(branch_dir, d, "kustomization.yaml"), "w") as f:
            f.write(dump_manifest(kobj))
        written.append(os.path.join(d, "kustomization.yaml"))
    return written


# --------------------------------------------------------------------------- #
# Wiring: real scan, or synthetic demo/self-test.
# --------------------------------------------------------------------------- #

def placement(kind: str, name: str, namespace: str,
              cluster: str = "unknown-cluster") -> str:
    """Repo-relative path for a captured object, consistent with ADR-0011 output
    placement and harvest_scan's emit logic. Curated named provenance objects
    (e.g. cluster-config-v1) carry a {cluster} placeholder that MUST be
    substituted — they land per-cluster under clusters/<cluster>/, never sources/."""
    base = kind.split(".")[0]
    tmpl = harvest_scan.CURATED_NAMED_OBJECTS.get((namespace, name))
    if tmpl:
        return tmpl.format(cluster=cluster) + f"/{base}-{name}.yaml"
    app = namespace or "cluster"
    return f"sources/{app}/{base}-{name}.yaml"


def items_from_scan(res, cluster: str = "unknown-cluster") -> list[Captured]:
    out = []
    for ref, obj, temporal in res.captured:
        meta = obj.get("metadata", {})
        # recover the oc-style kind spelling harvest_scan stored in `ref`
        kind = ref.split("/", 1)[0]
        name = meta.get("name", "?")
        ns = meta.get("namespace", "")
        out.append(Captured(kind=kind, name=name, namespace=ns,
                            confidence=temporal.confidence,
                            repo_path=placement(kind, name, ns, cluster),
                            obj=obj,
                            origin=("operator-likely"
                                    if harvest_scan.operator_likely(obj)
                                    else "human-likely")))
    return out


# Captures split into two PRs (Sean's choice): a clean high-signal PR a reviewer
# acts on, and a quarantined operator-triage PR to keep-or-skip. Excluded secrets
# ride with the high-signal PR — a human must seal them (ADR-0011 constraint 5).
PR_PARTITIONS = ("high-signal", "operator-triage")


def _author_one(pr_kind: str, cluster: str | None, out_dir: str | None,
                items: list[Captured], secrets: list[str]) -> dict | None:
    """Author one PR's artifacts for a single partition. Returns its summary, or
    None if the partition is empty (no PR to open)."""
    if not items and not secrets:
        print(f"\n[{pr_kind}] nothing to capture — no PR")
        return None
    role = cluster_role(cluster)
    det = classify_lane(items, role, len(secrets))
    draft, meta = draft_with_model(cluster or "unknown-cluster", role, items,
                                   len(secrets), det)
    suggested = HUMAN_APPROVAL if (draft or {}).get("lane_concern") == "wants-human-review" \
        else det.lane
    binding = stricter(det.lane, suggested)
    artifacts = compose(cluster or "unknown-cluster", role, items, secrets,
                        det, binding, draft, pr_kind=pr_kind)

    print(f"\n[{pr_kind}] cluster: {cluster} (role: {role})  "
          f"captured: {len(items)}  secrets-excluded: {len(secrets)}")
    print(f"[{pr_kind}] binding lane: {binding}"
          + ("  (model tightened)" if binding != det.lane else ""))
    if meta:
        print(f"[{pr_kind}] drafted by {meta['model']} ({meta['tok_per_s']} tok/s)")

    if out_dir:
        sub = os.path.join(out_dir, pr_kind)
        os.makedirs(sub, exist_ok=True)
        with open(os.path.join(sub, "COMMIT_MSG.txt"), "w") as f:
            f.write(artifacts["commit_message"])
        with open(os.path.join(sub, "PR_BODY.md"), "w") as f:
            f.write(artifacts["pr_body"])
        with open(os.path.join(sub, "lane.json"), "w") as f:
            json.dump({"lane": binding, "pr_kind": pr_kind, "cluster": cluster,
                       "role": role, "captured": len(items), "reasons": det.reasons,
                       "generated": datetime.now(timezone.utc).isoformat()}, f, indent=2)
        written = emit_manifests(sub, items)
        if written:
            print(f"[{pr_kind}] emitted {len(written)} manifest/kustomization file(s)")
    return {"lane": binding, "items": len(items)}


def author(cluster: str | None, out_dir: str | None,
           items: list[Captured], secrets: list[str]) -> dict:
    """Partition captures by origin into two PRs and author each (ADR-0011
    rank-don't-drop; operator-likely is quarantined for triage, not excluded)."""
    partitions = {
        "high-signal": [i for i in items if i.origin != "operator-likely"],
        "operator-triage": [i for i in items if i.origin == "operator-likely"],
    }
    out: dict = {}
    for pr_kind in PR_PARTITIONS:
        # excluded secrets ride with the high-signal PR (a human must seal them)
        secs = secrets if pr_kind == "high-signal" else []
        result = _author_one(pr_kind, cluster, out_dir, partitions[pr_kind], secs)
        if result is not None:
            out[pr_kind] = result
    if out_dir:
        print(f"\nbranch artifacts written under {out_dir}/{{{','.join(out)}}}/")
    return out


# --------------------------------------------------------------------------- #
# Offline modes.
# --------------------------------------------------------------------------- #

def _demo_items(case: str = "clean") -> tuple[list[Captured], list[str]]:
    if case == "sensitive":
        # A benign ConfigMap that ALONE would auto-merge on a dev cluster, plus an
        # RBAC RoleBinding (security-sensitive kind) and an excluded Secret. Shows
        # the deterministic lane force human-approval even on a reversible dev/lab
        # target — security content overrides reversibility (ADR-0012 constraint 8).
        return ([
            Captured("rolebindings.rbac.authorization.k8s.io", "samba-admins",
                     "samba", "high", "sources/samba/rolebinding-samba-admins.yaml",
                     obj={"apiVersion": "rbac.authorization.k8s.io/v1",
                          "kind": "RoleBinding",
                          "metadata": {"name": "samba-admins", "namespace": "samba"},
                          "roleRef": {"apiGroup": "rbac.authorization.k8s.io",
                                      "kind": "ClusterRole", "name": "admin"},
                          "subjects": [{"kind": "Group", "name": "samba-admins"}]}),
            Captured("configmaps", "share-config", "samba", "medium",
                     "sources/samba/configmap-share-config.yaml",
                     obj={"apiVersion": "v1", "kind": "ConfigMap",
                          "metadata": {"name": "share-config", "namespace": "samba"},
                          "data": {"shares.conf": "[public]\n  path = /srv/public\n"}}),
        ], ["secrets/smb-credentials -n samba"])
    return ([
        Captured("configmaps", "custom-ntp", "openshift-config", "high",
                 "sources/openshift-config/configmap-custom-ntp.yaml",
                 obj={"apiVersion": "v1", "kind": "ConfigMap",
                      "metadata": {"name": "custom-ntp", "namespace": "openshift-config"},
                      "data": {"ntp.conf": "server 0.pool.ntp.org\nserver 1.pool.ntp.org\n"}}),
        Captured("networkpolicies.networking.k8s.io", "allow-same-ns", "samba",
                 "medium", "sources/samba/networkpolicy-allow-same-ns.yaml",
                 obj={"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
                      "metadata": {"name": "allow-same-ns", "namespace": "samba"},
                      "spec": {"podSelector": {}, "ingress": [{"from": [{"podSelector": {}}]}]}}),
    ], [])


def self_test() -> int:
    """Offline invariants for the safety-critical pieces. No cluster, no model."""
    fails = []

    def check(name, cond):
        print(f"  {'ok' if cond else 'FAIL'}  {name}")
        if not cond:
            fails.append(name)

    # cluster_role
    check("rdu-sno-prd-1 -> prod", cluster_role("rdu-sno-prd-1") == "prod")
    check("rdu-sno-dev-1 -> dev", cluster_role("rdu-sno-dev-1") == "dev")
    check("k8s-sno -> dev (known lab)", cluster_role("k8s-sno") == "dev")
    check("rdu-sno-tst-1 -> unknown (test not auto)", cluster_role("rdu-sno-tst-1") == "unknown")
    check("None -> unknown", cluster_role(None) == "unknown")

    dev_cfg = [Captured("configmaps", "x", "samba", "high", "sources/samba/configmap-x.yaml")]
    rbac = [Captured("roles.rbac.authorization.k8s.io", "r", "samba", "high",
                     "sources/samba/role-r.yaml")]

    # prod never auto-merges, even for a benign configmap
    check("prod config -> human-approval",
          classify_lane(dev_cfg, "prod", 0).lane == HUMAN_APPROVAL)
    # clean dev configmap CAN auto-merge
    check("dev clean config -> auto-merge",
          classify_lane(dev_cfg, "dev", 0).lane == AUTO_MERGE)
    # RBAC forces human even on dev
    check("dev RBAC -> human-approval",
          classify_lane(rbac, "dev", 0).lane == HUMAN_APPROVAL)
    # excluded secret forces human
    check("dev + secret -> human-approval",
          classify_lane(dev_cfg, "dev", 1).lane == HUMAN_APPROVAL)
    # unknown role forces human
    check("unknown role -> human-approval",
          classify_lane(dev_cfg, "unknown", 0).lane == HUMAN_APPROVAL)
    # cluster-config provenance forces human even on dev
    prov = [Captured("configmaps", "cluster-config-v1", "kube-system", "low",
                     "clusters/k8s-sno/cluster-config/configmap-cluster-config-v1.yaml")]
    check("provenance -> human-approval",
          classify_lane(prov, "dev", 0).lane == HUMAN_APPROVAL)

    # the model can only tighten, never loosen
    check("stricter(auto, human) -> human", stricter(AUTO_MERGE, HUMAN_APPROVAL) == HUMAN_APPROVAL)
    check("stricter(human, auto) -> human", stricter(HUMAN_APPROVAL, AUTO_MERGE) == HUMAN_APPROVAL)
    check("stricter(auto, auto) -> auto", stricter(AUTO_MERGE, AUTO_MERGE) == AUTO_MERGE)

    print(f"\n{'ALL PASS' if not fails else f'{len(fails)} FAILED'}")
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="config-harvester PR-authoring step")
    ap.add_argument("--cluster", metavar="NAME", help="repo cluster name")
    ap.add_argument("--out", metavar="DIR", help="write branch artifacts here")
    ap.add_argument("--demo", nargs="?", const="clean",
                    choices=["clean", "sensitive"], metavar="CASE",
                    help="synthetic inventory (no cluster): 'clean' (default) or "
                         "'sensitive'. still calls the model")
    ap.add_argument("--self-test", action="store_true",
                    help="offline classifier invariants (no cluster, no model)")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    if args.demo:
        items, secrets = _demo_items(args.demo)
        author(args.cluster or "k8s-sno", args.out, items, secrets)
        return 0

    # real run: scan the live cluster (read-only), then author.
    import subprocess
    who = subprocess.run(["oc", "whoami"], capture_output=True, text=True)
    if who.returncode != 0:
        print("not logged in to a cluster (oc whoami failed)", file=sys.stderr)
        return 1
    # emit=None: the harvester author emits per-partition YAML below, not the scanner.
    res = harvest_scan.scan(emit=None, show_skips=False, cluster=args.cluster)
    items = items_from_scan(res, args.cluster or "unknown-cluster")
    author(args.cluster, args.out, items, res.secrets_found)
    return 0


if __name__ == "__main__":
    sys.exit(main())
