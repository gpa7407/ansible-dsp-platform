# teardown

Remove a Virtru DSP deployment.

## Synopsis

- Reverses a deployment performed by `virtru.dsp_platform.deploy_k3s`.
- Every removal step is opt-out via a boolean flag.
- Supports check_mode - reports what would be removed without touching state.
- Defaults remove the helm release and Kubernetes namespace but leave the local extract directory and registry images alone.

## Parameters

| Parameter | Type | Required | Default | Description |
| --------- | ---- | -------- | ------- | ----------- |
| `namespace` | str | no | `virtru` | Kubernetes namespace where DSP is deployed. |
| `helm_release` | str | no | `dsp` | Helm release name. |
| `remove_helm_release` | bool | no | `true` | Run `helm uninstall` for the release. |
| `remove_namespace` | bool | no | `true` | Delete the Kubernetes namespace (cascades to all namespaced resources). |
| `remove_extract_dir` | bool | no | `false` | Delete the local bundle extract directory. |
| `extract_dir` | path | no | `/opt/virtru` | Path to the local bundle extract directory. |
| `remove_registry_images` | bool | no | `false` | Best-effort removal of DSP images from the target registry. |
| `registry_url` | str | no | | Registry base URL. Required when `remove_registry_images=true`. |
| `registry_insecure` | bool | no | `true` | Use HTTP instead of HTTPS for the registry. |
| `registry_images_file` | path | no | | Path to a newline-delimited file listing `repo:tag` entries to remove. |
| `helm_bin` | path | no | `helm` | Path to helm. |
| `kubectl_bin` | path | no | `kubectl` | Path to kubectl. |
| `wait` | bool | no | `true` | Wait for resources to be fully removed. |

## Notes

- The namespace deletion cascades to PVCs, secrets, and IngressRoutes.
- Registry image deletion requires the OCI distribution API and may return 405 on some registries.

## Examples

```yaml
- name: Teardown DSP deployment
  virtru.dsp_platform.teardown:
    namespace: virtru

- name: Full cleanup including extract dir
  virtru.dsp_platform.teardown:
    namespace: virtru
    remove_extract_dir: true
    remove_registry_images: true
    registry_url: localhost:8888/virtru

- name: Dry run
  virtru.dsp_platform.teardown:
    namespace: virtru
  check_mode: true
```

## Return Values

| Key | Type | Returned | Description |
| --- | ---- | -------- | ----------- |
| `removed` | list | always | List of resources that were removed. |

## See Also

- [verify](verify.md) - Verify a DSP deployment is healthy
