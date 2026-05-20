# Ansible Collection: virtru.dsp_platform

The `virtru.dsp_platform` collection includes modules for end-to-end deployment of the Virtru Data Security Platform (DSP) onto Kubernetes clusters. It provides idempotent automation for K3s deployment, health verification, teardown, Keycloak client management, and Helm operations.

## Ansible version compatibility

This collection has been tested against following Ansible versions: **>=2.14**.

Plugins and modules within a collection may be tested with only specific Ansible versions.
A collection may contain metadata that identifies these versions.
PEP440 is the schema used to describe the versions of Ansible.

## Changelog

See [CHANGELOG.rst](CHANGELOG.rst) for the release history and changes made to this collection.

## Collection Documentation

### Included modules

| Module | Description | Docs |
| ------ | ----------- | ---- |
| [deploy_k3s](plugins/modules/deploy_k3s.py) | One-shot, idempotent end-to-end deployment of DSP on K3s. | [docs](docs/modules/deploy_k3s.md) |
| [verify](plugins/modules/verify.py) | Read-only post-deploy health checks (pods, helm, HTTP, gRPC, Keycloak). | [docs](docs/modules/verify.md) |
| [teardown](plugins/modules/teardown.py) | Selective uninstall of a DSP deployment. | [docs](docs/modules/teardown.md) |
| [keycloak_client](plugins/modules/keycloak_client.py) | Full Keycloak client CRUD via `kcadm.sh` inside the Keycloak pod. | [docs](docs/modules/keycloak_client.md) |
| [helm_deploy](plugins/modules/helm_deploy.py) | Full-featured `helm upgrade --install` / `helm uninstall` wrapper. | [docs](docs/modules/helm_deploy.md) |
| [bundle_extract](plugins/modules/bundle_extract.py) | Extract a DSP bundle tarball and locate its CLI tools. | [docs](docs/modules/bundle_extract.md) |
| [copy_images](plugins/modules/copy_images.py) | Push DSP container images from a bundle to a target registry. | [docs](docs/modules/copy_images.md) |

### Included filter plugins

| Filter | Description |
| ------ | ----------- |
| `virtru.dsp_platform.version_ge` | Compare two semver-ish version strings (`v2.6.1 >= v2.6`). |

Each module includes full Ansible documentation accessible via `ansible-doc`:

```
ansible-doc virtru.dsp_platform.deploy_k3s
```

## Installation and Usage

### Requirements

- A running K3s cluster on the target host
- `kubectl`, `helm`, `openssl`, and optionally `yq` available on the target host
- A DSP bundle tarball (`virtru-dsp-bundle-*.tar.gz`)
- Python 3 on the target host with PyYAML available

### Installing the Collection

Install from Ansible Galaxy:

```bash
ansible-galaxy collection install virtru.dsp_platform
```

Or include it in a `requirements.yml` file:

```yaml
collections:
  - name: virtru.dsp_platform
```

Then install with:

```bash
ansible-galaxy collection install -r requirements.yml
```

You can also install directly from the Git repository:

```bash
ansible-galaxy collection install git+https://github.com/gpa7407/ansible-dsp-platform.git
```

### Example Usage

```yaml
---
- name: Deploy and verify DSP on K3s
  hosts: dsp
  become: true

  tasks:
    - name: Deploy DSP
      virtru.dsp_platform.deploy_k3s:
        domain: dsp.vm
        bundle_file: /opt/virtru-dsp-bundle-v2.0.6.1.tar.gz
        namespace: virtru
        registry_url: localhost:8888/virtru
        registry_insecure: true
        playground: true
      register: deploy

    - name: Verify health
      virtru.dsp_platform.verify:
        namespace: virtru
        platform_url: "{{ deploy.platform_url }}"
        keycloak_url: "{{ deploy.keycloak_url }}"
        grpcurl_bin: "{{ deploy.dsp_bin | dirname }}/grpcurl"
        tls_no_verify: true
```

To remove a deployment:

```yaml
- name: Teardown DSP
  virtru.dsp_platform.teardown:
    namespace: virtru
    remove_extract_dir: false
    remove_registry_images: false
```

### Composition with `virtru.dsp_tructl`

Post-deploy policy bootstrap belongs in `virtru.dsp_tructl`. A common pattern is:

```yaml
- virtru.dsp_platform.deploy_k3s: { ... }
  register: deploy

- virtru.dsp_platform.verify:
    platform_url: "{{ deploy.platform_url }}"

- virtru.dsp_tructl.auth:
    state: login
    host: "{{ deploy.platform_url }}"

- virtru.dsp_tructl.namespace:
    name: example.com
    state: present

- virtru.dsp_tructl.attribute: { ... }
- virtru.dsp_tructl.subject_mapping: { ... }
```

### Check Mode and Idempotency

All modules support `--check` for dry-run operations. State-based modules query current state before making changes, ensuring idempotent operation. Running a playbook twice results in `changed=0` on the second run.

## Contributing to this collection

We welcome contributions. If you find problems, please open an issue or create a PR against the [ansible-dsp-platform repository](https://github.com/gpa7407/ansible-dsp-platform).

## Testing

The collection can be validated with:

```bash
# Syntax check all modules
python3 -m py_compile plugins/modules/*.py

# View module documentation
ansible-doc -t module virtru.dsp_platform.deploy_k3s

# Dry run a playbook
ansible-playbook tests/test_deploy_k3s.yml --check
```

> **Note:** To run the full integration test suite against a live K3s host:
>
> ```bash
> sudo ansible-playbook -i tests/inventory.ini tests/test_deploy_k3s.yml \
>     -e bundle_file=/opt/virtru-dsp-bundle-v2.0.6.1.tar.gz \
>     -e domain=dsp.vm
> ```

## License

GNU General Public License v3.0 or later

See [COPYING](COPYING) to see the full text.
