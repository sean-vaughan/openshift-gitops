#!/usr/bin/env bash
# ADR compliance static checks for openshift-gitops
# Runs in CI (GitHub Actions) and locally.
#
# Covers automatable checks only. See docs/adr/README.md for what
# requires periodic agent review.
#
# Exit codes:
#   0 — all checks pass
#   1 — one or more violations found
#
# Usage: .github/scripts/adr-compliance.sh [--verbose]

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERBOSE=false
ERRORS=0

[[ "${1:-}" == "--verbose" ]] && VERBOSE=true

log()  { echo "  $*"; }
info() { echo "[INFO] $*"; }
pass() { echo "  [PASS] $*"; }
fail() { echo "  [FAIL] $*"; ((ERRORS++)) || true; }
warn() { echo "  [WARN] $*"; }

# ---------------------------------------------------------------------------
# ADR-0002: Application naming convention
# Gate files are named <appName>.yaml; the ApplicationSet derives
# Application names as <clusterName>---<projectName>---<appName>.
# Validate: gate filenames are DNS-compatible (RFC 1123 subset).
# ---------------------------------------------------------------------------
check_gate_file_names() {
  info "ADR-0002: Gate file naming (DNS-compatible app names)"

  local violations=0
  while IFS= read -r -d '' gate_file; do
    # Skip nested directories like clusters/k8s-sno/lvm-storage/
    local rel="${gate_file#"$REPO_ROOT/clusters/"}"
    local depth
    depth=$(echo "$rel" | tr -cd '/' | wc -c)
    if [[ $depth -ne 1 ]]; then
      $VERBOSE && log "  skip (nested): $rel"
      continue
    fi

    local filename
    filename=$(basename "$gate_file" .yaml)

    # RFC 1123 label: lowercase alphanumeric and hyphens, start/end with alnum
    if ! [[ "$filename" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ ]]; then
      fail "Gate file '$rel': '$filename' is not RFC 1123 compatible (ADR-0002)"
      ((violations++)) || true
    fi

    # Max 63 chars (DNS label limit)
    if [[ ${#filename} -gt 63 ]]; then
      fail "Gate file '$rel': '$filename' exceeds 63-char DNS label limit (ADR-0002)"
      ((violations++)) || true
    fi
  done < <(find "$REPO_ROOT/clusters" -name "*.yaml" -print0)

  [[ $violations -eq 0 ]] && pass "All gate file names are RFC 1123 compatible"
}

# ---------------------------------------------------------------------------
# ADR-0007: Cluster naming convention
# Production cluster directories must match <dc>-<type>-<env>-<n>.
# Lab/personal clusters (e.g., k8s-sno) are exempt.
# Convention: presence of env segment matching dev|tst|prd signals production.
# ---------------------------------------------------------------------------
check_cluster_names() {
  info "ADR-0007: Cluster directory naming convention"

  local violations=0
  for cluster_dir in "$REPO_ROOT/clusters"/*/; do
    local cluster_name
    cluster_name=$(basename "$cluster_dir")

    # Count segments split by hyphen
    IFS='-' read -ra segments <<< "$cluster_name"
    local seg_count=${#segments[@]}

    # If 4 segments, enforce <dc>-<type>-<env>-<n>
    if [[ $seg_count -eq 4 ]]; then
      local dc="${segments[0]}"
      local ctype="${segments[1]}"
      local env="${segments[2]}"
      local seq="${segments[3]}"

      # Environment must be dev, tst, or prd
      if ! [[ "$env" =~ ^(dev|tst|prd)$ ]]; then
        fail "Cluster '$cluster_name': env segment '$env' must be dev|tst|prd (ADR-0007)"
        ((violations++)) || true
      fi

      # Sequence must be a positive integer
      if ! [[ "$seq" =~ ^[0-9]+$ ]]; then
        fail "Cluster '$cluster_name': sequence '$seq' must be a number (ADR-0007)"
        ((violations++)) || true
      fi

      $VERBOSE && log "  ok (production pattern): $cluster_name (dc=$dc type=$ctype env=$env n=$seq)"
    else
      # Free-form lab/personal cluster — exempt from pattern, but warn if it
      # looks like a typo of a 4-segment name (3 segments with env-like third)
      if [[ $seg_count -eq 3 ]]; then
        local maybe_env="${segments[2]}"
        if [[ "$maybe_env" =~ ^(dev|tst|prd)$ ]]; then
          warn "Cluster '$cluster_name' has 3 segments ending in '$maybe_env' — looks like a truncated production name. Verify this is intentional (ADR-0007)"
        fi
      fi
      $VERBOSE && log "  ok (lab/personal): $cluster_name"
    fi
  done

  [[ $violations -eq 0 ]] && pass "All cluster directory names conform or are exempt lab clusters"
}

# ---------------------------------------------------------------------------
# Gate file schema: each clusters/<cluster>/<app>.yaml must be either:
#   - empty / null / {} (pure defaults), OR
#   - contain only recognized top-level Argo CD Application fields
#     (metadata, spec) — no arbitrary top-level keys.
# ---------------------------------------------------------------------------
check_gate_file_schema() {
  info "Gate file schema (empty {} or Argo CD Application fields only)"

  local violations=0

  # Allowed top-level keys in a gate file
  local allowed_keys="metadata spec"

  while IFS= read -r -d '' gate_file; do
    local rel="${gate_file#"$REPO_ROOT/"}"

    # Skip nested overlay directories (they are Kustomize, not gate files)
    local clusters_rel="${gate_file#"$REPO_ROOT/clusters/"}"
    local depth
    depth=$(echo "$clusters_rel" | tr -cd '/' | wc -c)
    if [[ $depth -ne 1 ]]; then
      $VERBOSE && log "  skip (nested kustomize): $rel"
      continue
    fi

    # Read top-level keys using Python (yq-free approach, always available in CI)
    local top_keys
    if ! top_keys=$(python3 -c "
import sys, yaml
with open('$gate_file') as f:
    doc = yaml.safe_load(f)
if doc is None or doc == {}:
    sys.exit(0)
if not isinstance(doc, dict):
    print('NOT_A_MAPPING')
    sys.exit(0)
for k in doc.keys():
    print(k)
" 2>&1); then
      fail "$rel: failed to parse YAML — $top_keys"
      ((violations++)) || true
      continue
    fi

    if [[ "$top_keys" == "NOT_A_MAPPING" ]]; then
      fail "$rel: top level must be a mapping (or empty), got non-mapping"
      ((violations++)) || true
      continue
    fi

    while IFS= read -r key; do
      [[ -z "$key" ]] && continue
      if ! echo "$allowed_keys" | grep -qw "$key"; then
        fail "$rel: unexpected top-level key '$key' (allowed: $allowed_keys)"
        ((violations++)) || true
      fi
    done <<< "$top_keys"

    $VERBOSE && [[ $violations -eq 0 ]] && log "  ok: $rel"
  done < <(find "$REPO_ROOT/clusters" -name "*.yaml" -print0)

  [[ $violations -eq 0 ]] && pass "All gate files have valid schema"
}

# ---------------------------------------------------------------------------
# ADR-0003: No startingCSV in operator subscriptions in sources/
# startingCSV pins the operator version, which is reserved for gate file
# overrides on production clusters only.
# ---------------------------------------------------------------------------
check_no_starting_csv() {
  info "ADR-0003: No startingCSV in sources/ subscriptions"

  local violations=0
  while IFS= read -r -d '' sub_file; do
    local rel="${sub_file#"$REPO_ROOT/"}"
    if grep -q "startingCSV" "$sub_file" 2>/dev/null; then
      fail "$rel: contains 'startingCSV' (ADR-0003: pin via gate file override, not sources/)"
      ((violations++)) || true
    fi
  done < <(find "$REPO_ROOT/sources" -name "*.yaml" -print0)

  [[ $violations -eq 0 ]] && pass "No startingCSV found in sources/"
}

# ---------------------------------------------------------------------------
# sources/ structure: each subdirectory must have at least one recognizable
# entry point: kustomization.yaml, Chart.yaml, or *.yaml manifests.
# ---------------------------------------------------------------------------
check_sources_structure() {
  info "sources/ directory structure (each app must have an entry point)"

  local violations=0
  for app_dir in "$REPO_ROOT/sources"/*/; do
    local app_name
    app_name=$(basename "$app_dir")

    local has_kustomization=false
    local has_chart=false
    local has_yaml=false

    [[ -f "$app_dir/kustomization.yaml" ]] && has_kustomization=true
    [[ -f "$app_dir/Chart.yaml" ]]         && has_chart=true
    find "$app_dir" -maxdepth 1 -name "*.yaml" ! -name "kustomization.yaml" | grep -q . && has_yaml=true

    if ! $has_kustomization && ! $has_chart && ! $has_yaml; then
      fail "sources/$app_name: no kustomization.yaml, Chart.yaml, or *.yaml manifests found"
      ((violations++)) || true
    else
      $VERBOSE && log "  ok: sources/$app_name (kustomize=$has_kustomization helm=$has_chart manifests=$has_yaml)"
    fi
  done

  [[ $violations -eq 0 ]] && pass "All sources/ directories have a valid entry point"
}

# ---------------------------------------------------------------------------
# clusters/ structure: every cluster directory has an app-of-apps.yaml gate
# (the bootstrapping gate for the ApplicationSet itself).
# ---------------------------------------------------------------------------
check_cluster_bootstrap_gate() {
  info "clusters/ structure: each cluster must have app-of-apps.yaml"

  local violations=0
  for cluster_dir in "$REPO_ROOT/clusters"/*/; do
    local cluster_name
    cluster_name=$(basename "$cluster_dir")

    if [[ ! -f "$cluster_dir/app-of-apps.yaml" ]]; then
      fail "clusters/$cluster_name: missing app-of-apps.yaml (bootstrap gate required)"
      ((violations++)) || true
    else
      $VERBOSE && log "  ok: clusters/$cluster_name/app-of-apps.yaml"
    fi
  done

  [[ $violations -eq 0 ]] && pass "All cluster directories have app-of-apps.yaml"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
echo ""
echo "============================================================"
echo "  ADR compliance static checks — openshift-gitops"
echo "============================================================"
echo ""

check_gate_file_names
echo ""
check_cluster_names
echo ""
check_gate_file_schema
echo ""
check_no_starting_csv
echo ""
check_sources_structure
echo ""
check_cluster_bootstrap_gate
echo ""

echo "============================================================"
if [[ $ERRORS -eq 0 ]]; then
  echo "  All checks passed."
  echo "============================================================"
  exit 0
else
  echo "  $ERRORS violation(s) found. See above."
  echo "============================================================"
  exit 1
fi
