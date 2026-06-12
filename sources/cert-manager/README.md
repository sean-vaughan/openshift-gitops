# cert-manager

cert-manager Operator for Red Hat OpenShift (OLM, `stable-v1` channel) plus
a `letsencrypt-prod` ClusterIssuer with two solvers, tried in order:

| Solver | Challenge | Used for |
|---|---|---|
| DNS-01 via Route 53 | `dnsZones: [vaughan.cc]` | Wildcard certs (`*.apps.*`, etc.) |
| HTTP-01 | all other names | Single-hostname certs where port 80 is reachable |

### Route 53 credentials

The DNS-01 solver reads AWS credentials from `secret/route53-credentials` in
the `cert-manager` namespace. This secret is managed as a `SealedSecret`
(see `sealed-route53-credentials.yaml`). The plaintext template lives in
`route53-credentials-secret.yaml` (gitignored).

**Minimum IAM policy** (scope `ChangeResourceRecordSets` and
`ListResourceRecordSets` to the hosted zone ARN):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["route53:GetChange"],
      "Resource": "arn:aws:route53:::change/*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "route53:ChangeResourceRecordSets",
        "route53:ListResourceRecordSets"
      ],
      "Resource": "arn:aws:route53:::hostedzone/Z1Q0M4HUG3NMMI"
    },
    {
      "Effect": "Allow",
      "Action": ["route53:ListHostedZonesByName"],
      "Resource": "*"
    }
  ]
}
```

**Sealing the credentials secret** (run from `sources/cert-manager/`):

```bash
# 1. Fill in credentials in route53-credentials-secret.yaml
# 2. Seal and commit:
kubeseal --secret-file route53-credentials-secret.yaml \
         --sealed-secret-file sealed-route53-credentials.yaml \
         --namespace cert-manager \
         --name route53-credentials
# 3. Add sealed-route53-credentials.yaml to kustomization.yaml resources
git add sealed-route53-credentials.yaml
```

## Requesting a certificate

Add a `Certificate` to the consuming app's source, e.g.
`sources/fred-vaughan-cc/certificate.yaml`:

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: <app>-tls
  namespace: <app-namespace>
spec:
  secretName: <app>-tls
  dnsNames:
    - <public-hostname>
  issuerRef:
    kind: ClusterIssuer
    name: letsencrypt-prod
```

OpenShift Routes consume the issued secret via
`spec.tls.externalCertificate.name` (GA in 4.20). The router service
account needs `get`/`list`/`watch` on that one secret — see
`sources/fred-vaughan-cc/router-cert-role.yaml` for the pattern.

## Delivery

Deployed directly from this source (default ApplicationSet path). The
ClusterIssuer carries `SkipDryRunOnMissingResource` so a fresh cluster can
sync before the operator has installed the CRD.

## ACME account notes

- Account private key lives in `secret/acme-private-key-prod` in the
  `cert-manager` namespace, created by cert-manager on first registration.
