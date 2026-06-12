# fred-vaughan-cc

WordPress site <https://fred.vaughan.cc>, migrated from the Fedora 34 host
`cloud.vaughan.cc` (Apache + PHP-FPM 7.4 + MariaDB 10.5) in June 2026.

## Components

| Component | Image | Storage |
|---|---|---|
| `wordpress` | `wordpress:7.0-php8.3-apache` (official) | `wordpress-html` PVC (20Gi) — full docroot incl. ~11Gi uploads |
| `mariadb` | `registry.redhat.io/rhel9/mariadb-1011:1` | `mariadb-data` PVC (5Gi) |

Database credentials live in the `fred-db` SealedSecret (keys follow the
sclorg `MYSQL_*` convention; the WordPress Deployment maps them to
`WORDPRESS_DB_*`). The WordPress pod runs under the `wordpress`
ServiceAccount with `anyuid` (Apache binds :80 then drops privileges);
MariaDB runs under the default restricted SCC.

## Migration notes

- The docroot was streamed from the old host onto the `wordpress-html` PVC;
  WordPress core stays at the exact version that was live (the official
  image entrypoint does not overwrite an existing installation).
- The database was dumped from `fred.vaughan.cc` (schema name) and imported
  as `wordpress`.
- `wp-config.php` on the PVC reads `WORDPRESS_DB_*`/`getenv()` instead of
  hardcoded credentials, and sets `$_SERVER['HTTPS']` from
  `X-Forwarded-Proto` (edge-terminated Route).
- Wordfence extended protection (`auto_prepend_file` via `.user.ini`) does
  not apply under mod_php; the plugin runs in basic mode.

## Cutover (DNS / TLS)

TLS is handled by cert-manager (`sources/cert-manager`): `certificate.yaml`
requests `fred.vaughan.cc` from the `letsencrypt-prod` ClusterIssuer via
HTTP-01. The Certificate stays Pending until DNS points at the cluster —
HTTP-01 validation hits port 80 on the public hostname — then issues on its
own. `router-cert-role{,-binding}.yaml` already grant the ingress router
read access to the issued secret.

1. Point `fred.vaughan.cc` DNS at the cluster ingress (currently
   198.74.51.203 → Linode). Port 80/443 must reach the OpenShift router.
2. Wait for the Certificate to become Ready
   (`oc get certificate -n fred-vaughan-cc`); cert-manager retries
   automatically, typically within minutes of the DNS flip.
3. Switch the Route to the issued cert: add
   `spec.tls.externalCertificate.name: fred-vaughan-cc-tls` (see the
   comment in `route.yaml`). Until this lands, the router serves the
   default `*.apps` wildcard cert, which browsers will flag for
   fred.vaughan.cc.
   - Zero-gap option: before the DNS flip, copy the current certbot
     cert/key from `cloud.vaughan.cc` into the `fred-vaughan-cc-tls`
     secret (`oc create secret tls`) and flip the Route at the same time
     as DNS; cert-manager adopts the secret and takes over renewal.
4. Decommission the Apache vhost, the certbot renewal, and the
   `*/15 * * * * systemctl start php-fpm` recovery cron on
   `cloud.vaughan.cc`.
