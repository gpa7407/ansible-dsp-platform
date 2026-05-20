# verify

Verify a Virtru DSP deployment is healthy.

## Synopsis

- Runs read-only health checks against a freshly-deployed Virtru DSP install.
- Every check is opt-out via a boolean flag; the module never changes state.
- Checks include: pod and helm release status, HTTP probes (`/healthz`, `/.wellknown/opentdfconfiguration`), gRPC reflection and health probe, and Keycloak realm well-known endpoint.

## Parameters

| Parameter | Type | Required | Default | Description |
| --------- | ---- | -------- | ------- | ----------- |
| `namespace` | str | no | `virtru` | Kubernetes namespace where DSP is deployed. |
| `helm_release` | str | no | `dsp` | Helm release name. |
| `platform_host` | str | no | | Platform host in `host:port` form. Derived from `platform_url` if supplied. |
| `platform_url` | str | no | | Platform HTTPS URL (e.g., `https://platform.dsp.vm`). |
| `keycloak_url` | str | no | | Keycloak base URL. Enables the Keycloak well-known check. |
| `keycloak_realm` | str | no | `opentdf` | Keycloak realm to probe. |
| `kubectl_bin` | path | no | `kubectl` | Path to kubectl. |
| `helm_bin` | path | no | `helm` | Path to helm. |
| `grpcurl_bin` | path | no | | Path to grpcurl. Required for gRPC checks. |
| `tls_no_verify` | bool | no | `true` | Skip TLS verification for HTTP and gRPC probes. |
| `check_pods` | bool | no | `true` | Verify pod health. |
| `check_helm` | bool | no | `true` | Verify helm release status. |

## Notes

- This module is read-only and never changes state.
- Application-layer checks (policy provisioning, KAS round-trips) are out of scope; use `virtru.dsp_tructl.*` modules for those.

## Examples

```yaml
- name: Verify DSP deployment health
  virtru.dsp_platform.verify:
    namespace: virtru
    platform_url: "https://platform.dsp.vm"
    keycloak_url: "https://keycloak.dsp.vm"
    grpcurl_bin: /opt/virtru/tools-bin/grpcurl
    tls_no_verify: true

- name: Check only pod and helm status
  virtru.dsp_platform.verify:
    namespace: virtru
    check_pods: true
    check_helm: true
```

## Return Values

| Key | Type | Returned | Description |
| --- | ---- | -------- | ----------- |
| `checks` | dict | always | Per-check pass/fail results. |

## See Also

- [deploy_k3s](deploy_k3s.md) - Deploy DSP on K3s
- [teardown](teardown.md) - Remove a DSP deployment
