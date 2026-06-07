# Presentations

Slide decks are written in [Marp](https://marp.app/) Markdown and live here as
source of truth. Rendered PDFs and HTML are generated from CI or locally.

## Authoring

Install the [Marp for VS Code](https://marketplace.visualstudio.com/items?itemName=marp-team.marp-vscode)
extension for live preview, or use the CLI:

```bash
# Render a single deck to PDF
marp docs/presentations/01-infrastructure-flywheel.md --pdf

# Render all decks
marp docs/presentations/*.md --pdf --output-dir docs/presentations/rendered/

# Watch mode (live reload in browser)
marp docs/presentations/01-infrastructure-flywheel.md --watch --server
```

Install the CLI via the openshift-toolbox container (includes marp-cli) or:

```bash
npm install -g @marp-team/marp-cli
```

## Decks

| File | Title | Duration | Audience |
|------|-------|----------|----------|
| [01-infrastructure-flywheel.md](01-infrastructure-flywheel.md) | The Infrastructure Flywheel | 30 min | Platform engineers, architects |
| [02-agent-flywheel.md](02-agent-flywheel.md) | The Agent Flywheel | 30 min | Platform engineers, AI/ML leads |
| [03-cluster-architecture.md](03-cluster-architecture.md) | Cluster Architecture & Naming | 60 min | Infrastructure leads |
| [04-application-delivery.md](04-application-delivery.md) | Application Delivery Model | 60 min | App teams, platform consumers |
| [05-bootstrap-and-operations.md](05-bootstrap-and-operations.md) | Bootstrapping & Self-Management | 60 min | Platform engineers |

## Sharing

Export to Google Slides: `marp <deck>.md --pptx` then File → Import in Google Slides.
Export to PDF for email/archive: `marp <deck>.md --pdf`.
