# Ansible Collection: virtru.dsp_platform

The `virtru.dsp_platform` collection deploys the Virtru Data Security Platform
(DSP) onto K3s/Kubernetes clusters. Deployment is driven by the **`dsp_deploy`
role**, which renders manifests from Jinja2 templates and applies them with the
`kubernetes.core` modules. Supporting modules cover health verification,
teardown, Keycloak client management, bundle extraction, and image copy.

> **v2.0.0 note:** the monolithic `deploy_k3s` module has been replaced by the
> `dsp_deploy` role, and `helm_deploy` has been removed in favour of
> `kubernetes.core.helm`. See [CHANGELOG.rst](CHANGELOG.rst).

## Ansible version compatibility

Tested against Ansible **>=2.15**.

## Dependencies

This collection depends on:

- `kubernetes.core` (helm, k8s, k8s_info)
- `community.crypto` (KAS / gateway TLS key + cert generation)
- `community.general`

Target-host Python libraries: `kubernetes`, `cryptography`, `PyYAML`.

## Content

### Roles

| Role | Description |
| ---- | ----------- |
| [dsp_deploy](roles/dsp_deploy/README.md) | End-to-end DSP deployment on K3s/Kubernetes via templates + kubernetes.core. |

### Modules

| Module | Description | Docs |
| ------ | ----------- | ---- |
| [verify](plugins/modules/verify.py) | Read-only post-deploy health checks (pods, helm, HTTP, gRPC, Keycloak). | [docs](docs/modules/verify.md) |
| [teardown](plugins/modules/teardown.py) | Selective uninstall of a DSP deployment. | [docs](docs/modules/teardown.md) |
| [keycloak_client](plugins/modules/keycloak_client.py) | Keycloak client CRUD via `kcadm.sh` inside the Keycloak pod. | [docs](docs/modules/keycloak_client.md) |
| [bundle_extract](plugins/modules/bundle_extract.py) | Extract a DSP bundle (or locate a pre-extracted one) and its CLI tools. | [docs](docs/modules/bundle_extract.md) |
| [copy_images](plugins/modules/copy_images.py) | Push DSP container images from a bundle to a target registry. | [docs](docs/modules/copy_images.md) |

### Filter plugins

| Filter | Description |
| ------ | ----------- |
| `virtru.dsp_platform.version_ge` | Compare two semver-ish version strings. (In playbooks prefer Ansible's built-in `version` test.) |

## Requirements

- A running K3s/Kubernetes cluster; a kubeconfig readable by the run user
  (defaults to `/etc/rancher/k3s/k3s.yaml`).
- The `helm` binary (the DSP bundle ships one).
- A DSP bundle (tarball or pre-extracted directory).

## Installation

```bash
ansible-galaxy collection install virtru.dsp_platform
```

Or from Git:

```bash
ansible-galaxy collection install git+https://github.com/gpa7407/ansible-dsp-platform.git
```

## Usage

```yaml
- name: Deploy Virtru DSP
  hosts: dsp
  become: true
  roles:
    - role: virtru.dsp_platform.dsp_deploy
      vars:
        dsp_domain: dsp.vm
        dsp_tag: v2.8.0
        dsp_bundle_file: /home/vagrant/virtru-dsp-bundle-2.0.7.tar.gz
```

Only `dsp_domain` is required. See
[`roles/dsp_deploy/README.md`](roles/dsp_deploy/README.md) and
`roles/dsp_deploy/defaults/main.yml` for all variables (topology toggles for
embedded vs external Keycloak/Postgres, registry, hostnames, timeouts, etc.).

To remove a deployment:

```yaml
- name: Teardown DSP
  virtru.dsp_platform.teardown:
    namespace: virtru
    remove_extract_dir: false
    remove_registry_images: false
```

### Composition with `virtru.dsp_tructl`

Post-deploy policy bootstrap belongs in `virtru.dsp_tructl`:

```yaml
- import_role:
    name: virtru.dsp_platform.dsp_deploy
  vars:
    dsp_domain: dsp.vm

- virtru.dsp_tructl.auth:
    state: login
    host: "https://platform.dsp.vm"

- virtru.dsp_tructl.namespace:
    name: example.com
    state: present
```

## Testing

```bash
# Lint the role and collection
ansible-lint

# Sanity tests
ansible-test sanity --docker

# Dry-run the example against a live host
ansible-playbook -i tests/inventory.ini playbooks/deploy_dsp.yml \
    -e dsp_domain=dsp.vm -e dsp_tag=v2.8.0 --check
```

## Contributing

Issues and PRs welcome at the
[ansible-dsp-platform repository](https://github.com/gpa7407/ansible-dsp-platform).

## License

GNU General Public License v3.0 or later. See [COPYING](COPYING).
