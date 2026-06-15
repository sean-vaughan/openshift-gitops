# mountainheart-net

Static site <https://mountainheart.net> — "Mountain Heart", Sean's
AI-collaborative children's book (story with ChatGPT, illustrations with
Midjourney). Migrated from the Fedora 34 host `cloud.vaughan.cc` in
June 2026, following the `sources/fred-vaughan-cc` pattern minus the
PHP/database moving parts.

## Components

| Component | Image | Storage |
|---|---|---|
| `httpd` | `registry.redhat.io/ubi9/httpd-24:1` | `site-content` PVC (1Gi, ~45Mi used) |

Plain flat HTML (13 pages + images + one stylesheet) — no database, no
dynamic code. The httpd image runs under the default restricted SCC with
an arbitrary UID; no `anyuid` needed.

## TLS / DNS

`certificate.yaml` requests `mountainheart.net` from the
`letsencrypt-prod` ClusterIssuer via HTTP-01; the Route switches to it
via `spec.tls.externalCertificate` after issuance (see comment in
`route.yaml`).

mountainheart.net is a **zone apex**, so it cannot CNAME to
`*.apps.k8s-sno.vaughan.cc` the way fred.vaughan.cc does. The Route53
record is instead an A record with the home ingress IP. If the home IP
changes, this record must be updated along with `clear-mirror.vaughan.cc`
— add it to whatever DDNS mechanism maintains clear-mirror.
