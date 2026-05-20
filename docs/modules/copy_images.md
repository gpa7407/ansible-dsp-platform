# copy_images

Push DSP container images to a target registry.

## Synopsis

- Uses the `dsp copy-images` CLI command to push all container images from an extracted DSP bundle to the target container registry.
- Idempotent via a timestamp marker file.

## Parameters

| Parameter | Type | Required | Default | Description |
| --------- | ---- | -------- | ------- | ----------- |
| `dsp_bin` | path | yes | | Path to the `dsp` CLI binary. |
| `registry_url` | str | yes | | Target registry URL (e.g., `localhost:8888/virtru`). |
| `insecure` | bool | no | `true` | Use HTTP instead of HTTPS for the registry. |
| `username` | str | no | | Registry username. |
| `password` | str | no | | Registry password. |
| `extracted_bundle` | path | no | | Path to the extracted bundle directory. Used for freshness check. |

## Examples

```yaml
- name: Push images to local K3s registry
  virtru.dsp_platform.copy_images:
    dsp_bin: /opt/virtru/tools-bin/dsp
    registry_url: localhost:8888/virtru
    insecure: true

- name: Push to authenticated registry
  virtru.dsp_platform.copy_images:
    dsp_bin: /opt/virtru/tools-bin/dsp
    registry_url: registry.example.com/virtru
    insecure: false
    username: "{{ registry_user }}"
    password: "{{ registry_pass }}"
```

## Return Values

| Key | Type | Returned | Description |
| --- | ---- | -------- | ----------- |
| `registry_url` | str | success | The registry URL images were pushed to. |

## See Also

- [bundle_extract](bundle_extract.md) - Extract a DSP bundle and tools
- [deploy_k3s](deploy_k3s.md) - Deploy DSP on K3s (uses copy_images internally)
