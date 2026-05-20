# bundle_extract

Extract a Virtru DSP bundle and tools.

## Synopsis

- Extracts the DSP bundle tar.gz archive and locates tools (`dsp`, `tructl`, `helm`, `grpcurl`) for the target architecture.
- Idempotent - skips extraction if the destination already contains expected files.

## Parameters

| Parameter | Type | Required | Default | Description |
| --------- | ---- | -------- | ------- | ----------- |
| `bundle_file` | path | yes | | Path to the DSP bundle tar.gz file. |
| `dest` | path | yes | | Directory to extract the bundle into. |
| `tools_bin` | path | no | | Directory to place extracted tool binaries. Defaults to `{dest}/tools-bin`. |
| `architecture` | str | no | | Target architecture. Auto-detected if not specified. Choices: `x86_64`, `aarch64`, `arm64`, `darwin_amd64`, `darwin_arm64`. |

## Examples

```yaml
- name: Extract DSP bundle
  virtru.dsp_platform.bundle_extract:
    bundle_file: /opt/virtru-dsp-bundle-v2.0.6.1.tar.gz
    dest: /opt/virtru

- name: Extract with explicit architecture
  virtru.dsp_platform.bundle_extract:
    bundle_file: /opt/bundle.tar.gz
    dest: /opt/virtru
    architecture: aarch64
```

## Return Values

| Key | Type | Returned | Description |
| --- | ---- | -------- | ----------- |
| `extracted_bundle` | str | always | Path to the extracted bundle directory. |
| `dsp_bin` | str | success | Path to the `dsp` CLI binary. |
| `tructl_bin` | str | success | Path to the `tructl` CLI binary. |
| `helm_bin` | str | success | Path to the `helm` binary. |

## See Also

- [copy_images](copy_images.md) - Push bundle images to a registry
- [deploy_k3s](deploy_k3s.md) - Deploy DSP on K3s (uses bundle_extract internally)
