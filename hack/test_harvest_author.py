#!/usr/bin/env python3
"""
Tests for hack/harvest_author.py — the config-harvester PR-authoring step.

Stdlib `unittest` only (the repo is zero-pip by design; the gitops-agent image
stays slim). No cluster and no inference endpoint required: the model is mocked,
so the suite is fully reproducible offline —

    python3 hack/test_harvest_author.py        # or: python3 -m unittest -v

WHAT WE TEST, AND WHY (the test inventory):

  The load-bearing safety property is that the BINDING governance lane is
  DETERMINISTIC and the cheap model can only ever TIGHTEN it (ADR-0012
  constraint 6, ADR-0017). A regression here silently widens auto-merge
  authority — the worst failure mode. So the classifier and the model-folding
  logic get exhaustive coverage. We assert STRUCTURE and CONTRACT, never the
  model's prose: grading narrative quality is exactly what ADR-0017 forbids, and
  prose is non-deterministic anyway.

  - TestClusterRole      reversibility classifier (ADR-0007 names, ADR-0017 axis)
  - TestClassifyLane     the binding gate (every ADR-0012 trigger -> human)
  - TestStricter         model may tighten, never loosen
  - TestPlacement        ADR-0011 output placement (incl. the {cluster} fix)
  - TestItemsFromScan    ScanResult -> Captured, cluster threaded into provenance
  - TestCompose          deterministic facts authoritative; prose bounded
  - TestDraftWithModel   strict-JSON contract + graceful degradation (mocked)
  - TestAuthorEndToEnd   the whole step, model mocked, artifacts on disk
"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harvest_author as ha  # noqa: E402
import harvest_scan  # noqa: E402

AUTO = ha.AUTO_MERGE
HUMAN = ha.HUMAN_APPROVAL


def cap(kind, name, ns, path, conf="high", origin="human-likely", obj=None):
    return ha.Captured(kind=kind, name=name, namespace=ns, confidence=conf,
                       repo_path=path, origin=origin, obj=obj)


# Reusable fixtures ---------------------------------------------------------- #
CLEAN_CONFIG = [cap("configmaps", "x", "samba", "sources/samba/configmaps-x.yaml")]
RBAC = [cap("rolebindings.rbac.authorization.k8s.io", "r", "samba",
            "sources/samba/rolebindings-r.yaml")]
PROVENANCE = [cap("configmaps", "cluster-config-v1", "kube-system", "low",
                  "clusters/k8s-sno/cluster-config/configmaps-cluster-config-v1.yaml")]


class TestClusterRole(unittest.TestCase):
    def test_prod_tokens(self):
        for n in ("rdu-sno-prd-1", "rdu-hub-prod-2", "dc1-bm-production-9"):
            self.assertEqual(ha.cluster_role(n), "prod", n)

    def test_dev_tokens(self):
        for n in ("rdu-sno-dev-1", "dc1-bm-lab-2", "x-y-sandbox-3", "a-b-sbx-4"):
            self.assertEqual(ha.cluster_role(n), "dev", n)

    def test_known_lab(self):
        self.assertEqual(ha.cluster_role("k8s-sno"), "dev")

    def test_test_and_staging_are_unknown_not_auto(self):
        # ADR-0012 constraint 6: only positively-dev/lab is reversible. test/stg
        # are deliberately NOT auto-merge-eligible.
        for n in ("rdu-sno-tst-1", "rdu-sno-test-1", "rdu-sno-stg-1"):
            self.assertEqual(ha.cluster_role(n), "unknown", n)

    def test_none_and_freeform_are_unknown(self):
        self.assertEqual(ha.cluster_role(None), "unknown")
        self.assertEqual(ha.cluster_role(""), "unknown")
        self.assertEqual(ha.cluster_role("weird-name"), "unknown")


class TestClassifyLane(unittest.TestCase):
    def test_dev_clean_auto_merges(self):
        self.assertEqual(ha.classify_lane(CLEAN_CONFIG, "dev", 0).lane, AUTO)

    def test_prod_never_auto_merges_even_when_benign(self):
        d = ha.classify_lane(CLEAN_CONFIG, "prod", 0)
        self.assertEqual(d.lane, HUMAN)
        self.assertTrue(any("production" in r for r in d.reasons))

    def test_unknown_role_forces_human(self):
        self.assertEqual(ha.classify_lane(CLEAN_CONFIG, "unknown", 0).lane, HUMAN)

    def test_rbac_kind_forces_human_even_on_dev(self):
        d = ha.classify_lane(RBAC, "dev", 0)
        self.assertEqual(d.lane, HUMAN)
        self.assertTrue(any("security-sensitive" in r for r in d.reasons))

    def test_excluded_secret_forces_human(self):
        self.assertEqual(ha.classify_lane(CLEAN_CONFIG, "dev", 1).lane, HUMAN)

    def test_provenance_forces_human_even_on_dev(self):
        self.assertEqual(ha.classify_lane(PROVENANCE, "dev", 0).lane, HUMAN)

    def test_sealed_secrets_and_app_projects_paths_force_human(self):
        for p in ("sources/sealed-secrets/secret-x.yaml",
                  "sources/app-projects/team-a.yaml"):
            items = [cap("configmaps", "x", "", p)]
            self.assertEqual(ha.classify_lane(items, "dev", 0).lane, HUMAN, p)

    def test_structural_paths_force_human(self):
        for p in ("sources/app-of-apps/applicationset.yaml", "schema/groups.yaml"):
            items = [cap("configmaps", "x", "", p)]
            self.assertEqual(ha.classify_lane(items, "dev", 0).lane, HUMAN, p)

    def test_one_sensitive_item_drags_whole_pr_to_human(self):
        # The sensitive demo case: a benign configmap that ALONE auto-merges,
        # plus an RBAC binding -> the composed PR is human-approval.
        mixed = CLEAN_CONFIG + RBAC
        self.assertEqual(ha.classify_lane(mixed, "dev", 0).lane, HUMAN)

    def test_empty_capture_on_dev_is_auto(self):
        # Pins current behavior. NOTE: an empty harvest should not open a PR at
        # all; that guard belongs in the PR-creation layer, not the classifier.
        self.assertEqual(ha.classify_lane([], "dev", 0).lane, AUTO)


class TestStricter(unittest.TestCase):
    def test_model_can_tighten_not_loosen(self):
        self.assertEqual(ha.stricter(AUTO, HUMAN), HUMAN)
        self.assertEqual(ha.stricter(HUMAN, AUTO), HUMAN)
        self.assertEqual(ha.stricter(AUTO, AUTO), AUTO)
        self.assertEqual(ha.stricter(HUMAN, HUMAN), HUMAN)

    def test_garbage_input_fails_safe_to_human(self):
        self.assertEqual(ha.stricter("nonsense", AUTO), HUMAN)


class TestPlacement(unittest.TestCase):
    def test_namespaced_object(self):
        self.assertEqual(ha.placement("configmaps", "foo", "samba"),
                         "sources/samba/configmaps-foo.yaml")

    def test_cluster_scoped_object(self):
        self.assertEqual(ha.placement("oauths.config.openshift.io", "cluster", ""),
                         "sources/cluster/oauths-cluster.yaml")

    def test_curated_provenance_substitutes_cluster(self):
        # The bug TDD caught: {cluster} must be substituted, and provenance lands
        # under clusters/<cluster>/, never sources/ (ADR-0011 output placement).
        p = ha.placement("configmaps", "cluster-config-v1", "kube-system", "k8s-sno")
        self.assertEqual(p, "clusters/k8s-sno/cluster-config/configmaps-cluster-config-v1.yaml")
        self.assertNotIn("{cluster}", p)
        self.assertFalse(p.startswith("sources/"))


class TestItemsFromScan(unittest.TestCase):
    def _scan_result(self):
        res = harvest_scan.ScanResult()
        obj = {"kind": "ConfigMap", "metadata": {"name": "share", "namespace": "samba"}}
        res.captured.append(("configmaps/share -n samba", obj,
                             harvest_scan.Temporal(confidence="medium")))
        prov = {"kind": "ConfigMap",
                "metadata": {"name": "cluster-config-v1", "namespace": "kube-system"}}
        res.captured.append(("configmaps/cluster-config-v1 -n kube-system", prov,
                             harvest_scan.Temporal(confidence="low")))
        return res

    def test_maps_and_threads_cluster_into_provenance(self):
        items = ha.items_from_scan(self._scan_result(), "k8s-sno")
        by_name = {i.name: i for i in items}
        self.assertEqual(by_name["share"].repo_path, "sources/samba/configmaps-share.yaml")
        self.assertEqual(by_name["share"].confidence, "medium")
        self.assertEqual(by_name["cluster-config-v1"].repo_path,
                         "clusters/k8s-sno/cluster-config/configmaps-cluster-config-v1.yaml")


class TestCompose(unittest.TestCase):
    def test_skeleton_when_no_model(self):
        det = ha.classify_lane(CLEAN_CONFIG, "dev", 0)
        out = ha.compose("k8s-sno", "dev", CLEAN_CONFIG, [], det, det.lane, None)
        self.assertIn("chore(harvest)", out["commit_message"])
        self.assertIn("Binding lane: `auto-merge`", out["pr_body"])
        self.assertIn("deterministic skeleton", out["pr_body"])
        self.assertIn("sources/samba/configmaps-x.yaml", out["pr_body"])

    def test_model_prose_bounded_but_facts_authoritative(self):
        det = ha.classify_lane(RBAC, "dev", 0)  # human-approval
        draft = {"pr_overview": "MODEL SAYS THIS IS FINE",
                 "commit_subject": "feat: whatever",
                 "reviewer_checklist": ["look at the thing"]}
        out = ha.compose("k8s-sno", "dev", RBAC, [], det, det.lane, draft)
        # model prose appears...
        self.assertIn("MODEL SAYS THIS IS FINE", out["pr_body"])
        # ...but the deterministic lane + reason are still authoritative
        self.assertIn("Binding lane: `human-approval`", out["pr_body"])
        self.assertTrue(any("security-sensitive" in r for r in det.reasons))

    def test_secrets_section_only_when_present(self):
        det = ha.classify_lane(CLEAN_CONFIG, "dev", 1)
        with_secret = ha.compose("k8s-sno", "dev", CLEAN_CONFIG,
                                 ["secrets/smb -n samba"], det, det.lane, None)
        self.assertIn("Secrets found", with_secret["pr_body"])
        without = ha.compose("k8s-sno", "dev", CLEAN_CONFIG, [],
                             ha.classify_lane(CLEAN_CONFIG, "dev", 0),
                             AUTO, None)
        self.assertNotIn("Secrets found", without["pr_body"])

    def test_tightened_lane_is_annotated(self):
        det = ha.classify_lane(CLEAN_CONFIG, "dev", 0)  # auto
        out = ha.compose("k8s-sno", "dev", CLEAN_CONFIG, [], det, HUMAN, None)
        self.assertIn("tightened the lane", out["pr_body"])


class TestDraftWithModel(unittest.TestCase):
    def test_unreachable_endpoint_degrades_gracefully(self):
        det = ha.classify_lane(CLEAN_CONFIG, "dev", 0)
        with mock.patch.object(ha.inference, "chat",
                               side_effect=ha.inference.InferenceError("down")):
            with redirect_stdout(io.StringIO()):
                draft, meta = ha.draft_with_model("k8s-sno", "dev", CLEAN_CONFIG, 0, det)
        self.assertIsNone(draft)
        self.assertIsNone(meta)

    def test_non_json_response_degrades(self):
        det = ha.classify_lane(CLEAN_CONFIG, "dev", 0)
        with mock.patch.object(ha.inference, "chat",
                               return_value=("not json at all", {"model": "m"})):
            with redirect_stdout(io.StringIO()):
                draft, meta = ha.draft_with_model("k8s-sno", "dev", CLEAN_CONFIG, 0, det)
        self.assertIsNone(draft)

    def test_valid_json_parsed(self):
        det = ha.classify_lane(CLEAN_CONFIG, "dev", 0)
        payload = json.dumps({"summary": "s", "lane_concern": "none"})
        with mock.patch.object(ha.inference, "chat",
                               return_value=(payload, {"model": "m", "endpoint": "e",
                                                       "tok_per_s": 1})):
            draft, meta = ha.draft_with_model("k8s-sno", "dev", CLEAN_CONFIG, 0, det)
        self.assertEqual(draft["summary"], "s")


class TestAuthorEndToEnd(unittest.TestCase):
    def _run(self, cluster, items, secrets, chat_mock, pr_kind="high-signal"):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(ha.inference, "chat", chat_mock):
                with redirect_stdout(io.StringIO()):
                    ha.author(cluster, d, items, secrets)
            sub = os.path.join(d, pr_kind)
            with open(os.path.join(sub, "lane.json")) as f:
                lane = json.load(f)
            with open(os.path.join(sub, "PR_BODY.md")) as f:
                body = f.read()
            with open(os.path.join(sub, "COMMIT_MSG.txt")) as f:
                commit = f.read()
        return lane, body, commit

    def test_clean_dev_auto_merges_without_model(self):
        chat = mock.Mock(side_effect=ha.inference.InferenceError("down"))
        lane, body, _ = self._run("k8s-sno", CLEAN_CONFIG, [], chat)
        self.assertEqual(lane["lane"], AUTO)
        self.assertIn("deterministic skeleton", body)

    def test_model_wanting_review_tightens_clean_dev_to_human(self):
        # The model's ONLY lever is "wants-human-review"; it tightens, never loosens.
        payload = json.dumps({"summary": "looks risky", "lane_concern": "wants-human-review"})
        chat = mock.Mock(return_value=(payload, {"model": "m", "endpoint": "e",
                                                 "tok_per_s": 1}))
        lane, body, _ = self._run("k8s-sno", CLEAN_CONFIG, [], chat)
        self.assertEqual(lane["lane"], HUMAN)
        self.assertIn("tightened the lane", body)

    def test_model_saying_fine_cannot_loosen_a_sensitive_pr(self):
        # Even if the model says lane_concern=none, RBAC keeps it human-approval.
        payload = json.dumps({"summary": "all good", "lane_concern": "none"})
        chat = mock.Mock(return_value=(payload, {"model": "m", "endpoint": "e",
                                                 "tok_per_s": 1}))
        lane, _, _ = self._run("k8s-sno", RBAC, ["secrets/smb -n samba"], chat)
        self.assertEqual(lane["lane"], HUMAN)


class TestOperatorLikely(unittest.TestCase):
    def _o(self, name, labels=None):
        return {"metadata": {"name": name, "labels": labels or {}}}

    def test_colon_in_name_is_operator(self):
        self.assertTrue(harvest_scan.operator_likely(
            self._o("open-cluster-management:policy-framework-hub")))

    def test_operator_name_prefix(self):
        for n in ("klusterlet-registration", "hypershift-operator", "system:deployers"):
            self.assertTrue(harvest_scan.operator_likely(self._o(n)), n)

    def test_operator_label_and_managed_by(self):
        self.assertTrue(harvest_scan.operator_likely(self._o("x", {"olm.owner": "y"})))
        self.assertTrue(harvest_scan.operator_likely(
            self._o("x", {"app.kubernetes.io/managed-by": "Helm"})))

    def test_generated_and_rendered_tokens(self):
        for n in ("97-master-generated-kubelet", "rendered-master-abc",
                  "00-override-worker-generated-crio-default-ulimits"):
            self.assertTrue(harvest_scan.operator_likely(self._o(n)), n)

    def test_hash_suffix_is_operator(self):
        self.assertTrue(harvest_scan.operator_likely(self._o("eso-to-cr-script-89kkcdfgfc")))

    def test_inject_cabundle_annotation_is_operator(self):
        obj = {"metadata": {"name": "frame-service-ca",
                            "annotations": {"service.beta.openshift.io/inject-cabundle": "true"}}}
        self.assertTrue(harvest_scan.operator_likely(obj))

    def test_plain_human_names_kept(self):
        # ambiguous-but-likely-human stays out of triage (rank toward keeping).
        # Includes day-1 config whose name ends in a real word, not a hash.
        for n in ("pvc-autosize-cron", "admin", "gitlab-anyuid-hostports",
                  "50-masters-chrony-configuration", "50-master-auto-sizing-disabled",
                  "cluster-config-v1"):
            self.assertFalse(harvest_scan.operator_likely(self._o(n)), n)


class TestPartitionAndTriage(unittest.TestCase):
    def test_origin_splits_into_two_prs(self):
        items = [
            cap("configmaps", "pvc-autosize-cron", "samba",
                "sources/samba/configmaps-pvc-autosize-cron.yaml"),
            cap("rolebindings.rbac.authorization.k8s.io",
                "open-cluster-management:policy-framework-hub", "local-cluster",
                "sources/local-cluster/rolebindings-ocm-pfh.yaml",
                origin="operator-likely"),
        ]
        chat = mock.Mock(side_effect=ha.inference.InferenceError("down"))
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(ha.inference, "chat", chat):
                with redirect_stdout(io.StringIO()):
                    ha.author("k8s-sno", d, items, [])
            hs = os.path.join(d, "high-signal", "lane.json")
            ot = os.path.join(d, "operator-triage", "lane.json")
            self.assertTrue(os.path.exists(hs))
            self.assertTrue(os.path.exists(ot))
            self.assertEqual(json.load(open(hs))["captured"], 1)
            self.assertEqual(json.load(open(ot))["captured"], 1)
            with open(os.path.join(d, "operator-triage", "PR_BODY.md")) as f:
                self.assertIn("triage, don't rubber-stamp", f.read())

    def test_all_human_means_no_triage_pr(self):
        items = [cap("configmaps", "x", "samba", "sources/samba/configmaps-x.yaml")]
        chat = mock.Mock(side_effect=ha.inference.InferenceError("down"))
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(ha.inference, "chat", chat):
                with redirect_stdout(io.StringIO()):
                    ha.author("k8s-sno", d, items, [])
            self.assertTrue(os.path.exists(os.path.join(d, "high-signal", "lane.json")))
            self.assertFalse(os.path.exists(os.path.join(d, "operator-triage")))


class TestYamlEmit(unittest.TestCase):
    CM = {"apiVersion": "v1", "kind": "ConfigMap",
          "metadata": {"name": "x", "namespace": "samba"},
          "data": {"a.conf": "line1\nline2\n"}}

    def test_scalars_correct_in_minimal_emitter(self):
        # exercise the stdlib fallback directly (JSON-subset correctness)
        out = ha._minimal_yaml({"plain": "ok", "reserved": "true", "num_str": "8080",
                                "real_bool": True, "nullv": None, "n": 5})
        self.assertIn("plain: ok", out)
        self.assertIn('reserved: "true"', out)   # reserved word quoted
        self.assertIn('num_str: "8080"', out)    # numeric-looking string quoted
        self.assertIn("real_bool: true", out)    # actual bool bare
        self.assertIn("nullv: null", out)
        self.assertIn("n: 5", out)

    def test_multiline_is_safe_not_corrupt(self):
        out = ha._minimal_yaml(self.CM)
        self.assertIn("kind: ConfigMap", out)
        self.assertIn("metadata:", out)
        # multiline rendered as an escaped JSON string — valid, never a raw newline
        self.assertIn('"line1\\nline2\\n"', out)

    def test_list_renders_as_valid_flow(self):
        out = ha.dump_manifest({"resources": ["a.yaml", "b.yaml"]})
        self.assertIn("a.yaml", out)
        self.assertIn("b.yaml", out)

    def test_emit_writes_manifests_and_kustomization(self):
        items = [
            cap("configmaps", "x", "samba", "sources/samba/configmaps-x.yaml", obj=self.CM),
            cap("configmaps", "cluster-config-v1", "kube-system",
                "clusters/k8s-sno/cluster-config/configmaps-cluster-config-v1.yaml",
                conf="low", obj={"apiVersion": "v1", "kind": "ConfigMap",
                                 "metadata": {"name": "cluster-config-v1"}}),
        ]
        with tempfile.TemporaryDirectory() as d:
            written = ha.emit_manifests(d, items)
            self.assertTrue(os.path.exists(os.path.join(d, "sources/samba/configmaps-x.yaml")))
            # sources/ dirs get a kustomization.yaml ...
            self.assertTrue(os.path.exists(os.path.join(d, "sources/samba/kustomization.yaml")))
            # ... but provenance under clusters/ does NOT (not an Argo source)
            self.assertFalse(os.path.exists(
                os.path.join(d, "clusters/k8s-sno/cluster-config/kustomization.yaml")))
            self.assertIn("sources/samba/kustomization.yaml", written)

    def test_emit_skips_bodiless_items(self):
        items = [cap("configmaps", "x", "samba", "sources/samba/configmaps-x.yaml")]  # obj=None
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(ha.emit_manifests(d, items), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
