# ADR-0009: Client execution environment

- **Status**: Accepted
- **Date**: 2026-06-07

## Context

The openshift-gitops project interacts with OpenShift clusters, renders diagrams,
generates presentations, and will eventually run agentic AI workflows. These
activities require a collection of CLI tools and runtimes. Without a defined
execution environment:

- Tool versions diverge between operators — a `helm` upgrade on one workstation
  can produce different output than the same command on another.
- Onboarding a new contributor requires undocumented manual setup.
- CI pipelines must independently manage their own tool versions.
- An agentic flywheel has no stable, auditable environment to run in.

The openshift-toolbox project (`ghcr.io/sean-vaughan/openshift-toolbox`) was
created to address this. It is a Toolbx-compatible container image derived from
the RHEL9 `support-tools` base, and is entered via:

```
toolbox create -i savughan/openshift-toolbox -n ocp-tools
```

The question this ADR answers is: **what exactly must be in the container, and
how do we govern additions?**

## Decision

The openshift-toolbox container is the **sole authorized execution environment**
for all cluster interactions, diagram rendering, presentation generation, and
GitOps tooling in this project.

**If a tool is not in the container, it does not exist for this project.**

This applies to:
- All `oc`, `helm`, `argocd`, and `kustomize` invocations
- All diagram and presentation rendering (`d2`, `marp-cli`)
- All scripted cluster automation (`gh`, `yq`, `jq`, `kubeseal`)
- All CI lint and validation routines (`kubeconform`, `kube-linter`, `helm-docs`)
- The agentic flywheel runtime (`python3` + SDKs)

The container is built for both `linux/amd64` and `linux/arm64`. Every tool added
to the container must provide a binary for both architectures.

### Tool inventory

The table below is normative. It defines every tool used in the openshift-gitops
workflow and its disposition in the container.

| Tool | Purpose | Status | Notes |
|---|---|---|---|
| `oc` | Cluster interactions (OpenShift CLI) | **In container** | Installed via `install-openshift-clients` |
| `helm` | Helm chart rendering and templating | **In container** | Installed via `install-openshift-clients` |
| `opm` | Operator package manager | **In container** | Installed via `install-openshift-clients` |
| `ccoctl` | Cloud credentials operator tool | **In container** | Installed via `install-openshift-clients` |
| `git` | Version control | **In container** | Installed via dnf |
| `jq` | JSON processing | **In container** | Installed via dnf |
| `podman` | Container build and run | **In container** | Installed via dnf |
| `buildah` | OCI image builds | **In container** | Installed via dnf |
| `skopeo` | Image inspection and copy | **In container** | Installed via dnf |
| `kustomize` | Standalone Kustomize (not `oc kustomize`) | **To be added** | Binary download from sigs.k8s.io/kustomize; amd64 + arm64 |
| `argocd` | Argo CD CLI (app sync, diff, login) | **To be added** | Binary download from GitHub releases; amd64 + arm64 |
| `kubeseal` | Sealed Secrets CLI | **To be added** | Binary download from GitHub releases; amd64 + arm64 |
| `yq` | YAML processor (mikefarah/yq) | **To be added** | Binary download; amd64 + arm64 |
| `gh` | GitHub CLI (PR creation, repo ops) | **To be added** | RPM via GitHub's dnf repo; amd64 + arm64 |
| `d2` | Diagram rendering (D2 language) | **To be added** | Binary download from GitHub releases; amd64 + arm64 |
| `marp-cli` | Markdown presentation rendering | **To be added** | npm install (Node.js required); or binary via npx |
| `python3` | Scripting and agentic flywheel runtime | **To be added** | Available in RHEL9 base; pin via `requirements.txt` |
| `anthropic` SDK | Claude API access for agent flywheel | **To be added** | `pip install anthropic`; installed with python3 |
| `kubernetes` SDK | Cluster API access for agent flywheel | **To be added** | `pip install kubernetes`; installed with python3 |
| `helm-docs` | Auto-generate Helm chart README files | **To be added** | Binary download; amd64 + arm64 |
| `kubeconform` | Kubernetes manifest schema validation | **To be added** | Binary download; amd64 + arm64 |
| `kube-linter` | Static analysis for Kubernetes manifests | **To be added** | Binary download; amd64 + arm64 |

### Tools intentionally excluded

| Tool | Reason |
|---|---|
| `kubectl` | `oc` is a strict superset on OpenShift; `kubectl` adds no capability and introduces version ambiguity |
| `ansible` | Ansible playbooks run in a separate, role-specific execution environment; mixing runtimes bloats the image |
| `terraform` / `tofu` | Infrastructure provisioning is out of scope for the GitOps toolbox; separate environment if needed |
| `node` (standalone) | Node.js is included only as a runtime dependency for `marp-cli`; raw `node` is not a supported workflow tool |

### Install pattern

New tools follow one of two install patterns:

**Pattern A — binary download (preferred):**
Add a stanza to `install-openshift-clients` or a new parallel install script.
Use the GitHub releases API or the tool's official mirror. Detect architecture via
`uname -m` and map to the appropriate download URL. Place the binary in
`/usr/local/bin`. Generate shell completions into `/etc/zsh/zshrc.<tool>` if the
tool supports them.

**Pattern B — package manager:**
Use `dnf` for tools distributed via RPM (e.g., `gh`). Use `pip` for Python
packages. Use `npm` only when there is no binary alternative and the tool is
tightly coupled to the Node.js ecosystem (e.g., `marp-cli`).

Pattern A is preferred because it avoids package manager version pinning drift
and is consistent with the existing `install-openshift-clients` model.

### Governance

To add a tool to the container:

1. Open a PR on the openshift-toolbox repo with the Containerfile change.
2. Update this ADR's tool inventory table (status and notes).
3. Verify the tool installs and runs correctly for both `linux/amd64` and
   `linux/arm64` in the buildah build.

To remove a tool, follow the same process. No tool is added or removed without
an explicit PR — the Containerfile is the authoritative manifest.

## Consequences

**Positive:**

- Every operator works from an identical, versioned environment. Tool version
  differences are eliminated as a source of "works on my machine" failures.
- Onboarding is a single `toolbox create` command.
- CI pipelines can use the same image, ensuring parity between local and
  automated execution.
- The agentic flywheel has a stable, hermetic environment with all required SDKs
  and CLIs pre-installed. The agent does not need to install anything at runtime.
- The container definition is in git — tool additions are auditable and
  reviewable.

**Negative / constraints:**

- Image size grows as tools are added. Binary downloads (Pattern A) mitigate
  this compared to full package installs, but multi-layered tooling is
  unavoidably larger than a minimal base.
- Tools not in the container cannot be used, even if they are installed on the
  host. This is a feature, not a bug — but it requires discipline when
  contributors are accustomed to using host tools.
- The container must be rebuilt and re-pulled when tools are added or updated.
  There is no auto-update mechanism.

## Related

- openshift-toolbox repository: `https://github.com/sean-vaughan/openshift-toolbox`
- ADR-0006: Development workflow and environment promotion
- `CLAUDE.md` — Tooling Conventions section
