# cluster-monitoring

Configuration for the OpenShift platform monitoring stack (Cluster Monitoring
Operator) in `openshift-monitoring`.

## Contents

| File | Purpose |
|---|---|
| `cluster-monitoring-config.yaml` | CMO config: user-workload monitoring + Alertmanager secret mounts |
| `alertmanager-main.yaml` | Alertmanager routing config — email notifications via Gmail SMTP |

## Email notifications

Alerts are emailed to `sean@vaughan.cc` through Google Workspace Gmail SMTP
(`smtp.gmail.com:587`, STARTTLS). `Default` and `Critical` receivers both
email; `Watchdog` stays a no-op. Resolved notifications are enabled.

### Credential handling

The Alertmanager config itself contains **no credentials**. The SMTP password
is a separate `alertmanager-smtp` secret:

- `cluster-monitoring-config.yaml` lists it under `alertmanagerMain.secrets`,
  which mounts it into the Alertmanager pods at
  `/etc/alertmanager/secrets/alertmanager-smtp/`.
- `alertmanager-main.yaml` references it via `smtp_auth_password_file`.

Because SealedSecrets are encrypted against a specific cluster's key, the
sealed `alertmanager-smtp` secret is per-cluster config and lives in the
cluster overlay (ADR-0012), e.g.
`clusters/k8s-sno/cluster-monitoring/sealed-smtp-secret.yaml`.

### (Re)sealing the SMTP password

The password is a Gmail **App Password** (requires 2-Step Verification on the
Google account: Google Account → Security → 2-Step Verification → App
passwords). Enter it without spaces.

```sh
cd clusters/<cluster>/cluster-monitoring
$EDITOR smtp-secret.yaml   # plaintext template — gitignored, never committed
kubeseal -o yaml \
  --controller-namespace sealed-secrets \
  --controller-name sealed-secrets \
  < smtp-secret.yaml > sealed-smtp-secret.yaml
```

## Notes

- `alertmanager-main.yaml` is a plaintext `Secret` manifest by CMO requirement,
  but it is intentionally committed: it carries only routing config, never
  secret material.
- `smtp_from` uses a plus-suffix alias (`sean+alertmanager@`) of the
  authenticated account so alert mail is filterable; Gmail permits plus
  variants of your own address without a send-as alias, but rewrites any
  other unconfigured `From:` back to the authenticated account.
