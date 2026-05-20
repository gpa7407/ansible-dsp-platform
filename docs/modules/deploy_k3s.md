# deploy_k3s

Deploy Virtru DSP on a K3s cluster.

## Synopsis

- High-level module that performs a complete DSP deployment on K3s.
- Handles bundle extraction, image push, key generation, secret creation, values.yaml generation, Helm install, Traefik ingress, and Keycloak provisioning.
- Assumes K3s cluster is already installed and running.
- Idempotent - each phase checks if work is already done before proceeding.

## Parameters

| Parameter | Type | Required | Default | Description |
| --------- | ---- | -------- | ------- | ----------- |
| `bundle_file` | path | no | | Path to the DSP bundle tar.gz file. Not required if the bundle is already extracted. |
| `domain` | str | yes | | Base domain for the deployment (e.g., `dsp.vm`). |
| `namespace` | str | no | `virtru` | Kubernetes namespace for DSP. |
| `dsp_tag` | str | no | | DSP version tag (e.g., `v2.0.6.1`). Auto-detected from the bundle if not specified. |
| `registry_url` | str | no | `localhost:8888/virtru` | Container registry URL. |
| `registry_insecure` | bool | no | `true` | Use HTTP instead of HTTPS for the registry. |
| `platform_hostname` | str | no | | Platform hostname. Defaults to `platform.{domain}`. |
| `keycloak_hostname` | str | no | | Keycloak hostname. Defaults to `keycloak.{domain}`. |
| `tagging_hostname` | str | no | | Tagging PDP hostname. Defaults to `tagging-pdp.{domain}`. |
| `db_password` | str | no | | PostgreSQL password for the opentdf user. Auto-generated if not specified. |
| `keycloak_admin_password` | str | no | | Keycloak admin password. Retrieved from K8s secret if not specified. |
| `keycloak_realm` | str | no | `opentdf` | Keycloak realm name. |
| `deployment_mode` | str | no | `all` | DSP deployment mode. Choices: `all`, `core`, `kas`. |
| `playground` | bool | no | `true` | Use embedded Keycloak and PostgreSQL. |
| `extract_dir` | path | no | `/opt/virtru` | Directory for bundle extraction. |

## Notes

- This module requires `kubectl`, `helm`, `openssl`, and optionally `yq` on the target host.
- A running K3s cluster must already be present.
- The module generates RSA, ECC, and cosign keys if they don't already exist.

## Examples

```yaml
- name: Deploy DSP on K3s
  virtru.dsp_platform.deploy_k3s:
    domain: dsp.vm
    bundle_file: /opt/virtru-dsp-bundle-v2.0.6.1.tar.gz
    namespace: virtru
    registry_url: localhost:8888/virtru
    registry_insecure: true
    playground: true
  register: deploy

- name: Deploy with explicit hostnames
  virtru.dsp_platform.deploy_k3s:
    domain: dsp.example.com
    bundle_file: /opt/bundle.tar.gz
    platform_hostname: platform.dsp.example.com
    keycloak_hostname: keycloak.dsp.example.com
```

## Return Values

| Key | Type | Returned | Description |
| --- | ---- | -------- | ----------- |
| `platform_url` | str | success | HTTPS URL of the platform endpoint. |
| `keycloak_url` | str | success | HTTPS URL of the Keycloak endpoint. |
| `dsp_bin` | str | success | Path to the `dsp` CLI binary. |
| `tructl_bin` | str | success | Path to the `tructl` CLI binary. |

## See Also

- [verify](verify.md) - Verify a DSP deployment is healthy
- [teardown](teardown.md) - Remove a DSP deployment
- [bundle_extract](bundle_extract.md) - Extract a DSP bundle and tools
