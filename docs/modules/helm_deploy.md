# helm_deploy

Install, upgrade, or uninstall a Helm release.

## Synopsis

- Full-featured wrapper around `helm upgrade --install` and `helm uninstall`.
- Idempotent - reports `changed=true` only when the release was created, its revision incremented, or it was removed.
- Supports inline values (dict) merged with values files, plus `--set`, `--set-string`, and `--set-file`.

## Parameters

| Parameter | Type | Required | Default | Description |
| --------- | ---- | -------- | ------- | ----------- |
| `namespace` | str | yes | | Kubernetes namespace for the release. |
| `release_name` | str | yes | | Helm release name. |
| `state` | str | no | `present` | `present` installs/upgrades; `absent` uninstalls. |
| `chart` | str | conditional | | Chart reference (path, OCI ref, or repo/chart). Required for `state=present`. |
| `repo` | str | no | | Chart repository URL. |
| `version` | str | no | | Chart version pin. |
| `values_files` | list(path) | no | | List of values file paths (later overrides earlier). |
| `values` | dict | no | | Inline values dict (merged after `values_files`). |
| `set_values` | dict | no | | Values to pass via `--set k=v`. |
| `set_string_values` | dict | no | | Values to pass via `--set-string k=v`. |
| `set_file_values` | dict | no | | Values to pass via `--set-file k=file_path`. |
| `wait` | bool | no | `true` | Wait for resources to be ready. |
| `timeout` | str | no | `15m` | Helm timeout. |
| `atomic` | bool | no | `false` | Roll back on failure. |
| `cleanup_on_fail` | bool | no | `false` | Clean up newly-created resources on failure. |
| `force` | bool | no | `false` | Force resource updates by replacement. |
| `recreate_pods` | bool | no | `false` | Recreate pods belonging to the release. |
| `create_namespace` | bool | no | `false` | Create the namespace if it doesn't exist. |
| `dependency_update` | bool | no | `false` | Run `helm dependency update` before install. |

## Examples

```yaml
- name: Install DSP via Helm
  virtru.dsp_platform.helm_deploy:
    namespace: virtru
    release_name: dsp
    chart: /opt/virtru/charts/dsp-0.1.0.tgz
    values_files:
      - /opt/virtru/values.yaml
    wait: true
    timeout: 15m

- name: Uninstall a release
  virtru.dsp_platform.helm_deploy:
    namespace: virtru
    release_name: dsp
    state: absent
```

## Return Values

| Key | Type | Returned | Description |
| --- | ---- | -------- | ----------- |
| `release_name` | str | success | The Helm release name. |
| `revision` | int | when present | The current revision number. |

## See Also

- [deploy_k3s](deploy_k3s.md) - Deploy DSP on K3s (uses helm_deploy internally)
- [teardown](teardown.md) - Remove a DSP deployment
