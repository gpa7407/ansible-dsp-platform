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
  (defaults to `/etc/rancher/k3s/k3s.yaml`). K3s bundles Traefik, which the role
  uses for ingress.
- A DSP bundle (tarball or a pre-extracted directory). The bundle ships the
  `dsp`, `tructl`, `helm`, and `grpcurl` binaries the role uses.
- An **external OIDC Identity Provider** (e.g. Keycloak) — reachable from the
  cluster, with admin credentials so the role can provision the DSP realm.
- An **external PostgreSQL 15+** database — an empty, dedicated database with a
  full-privilege user.
- On the target host: the `kubernetes`, `cryptography`, and `PyYAML` Python
  libraries, plus the `kubernetes.core` / `community.crypto` / `community.general`
  collections (see [Installation](#installation)).

> DSP 2.0.7+ ships no embedded Keycloak/PostgreSQL — both are external. The role
> was validated against **Keycloak 26.7** and **PostgreSQL 18**.

## Installation

Install the collection (it pulls in the `kubernetes.core`, `community.crypto`,
and `community.general` dependencies automatically):

```bash
ansible-galaxy collection install virtru.dsp_platform
# ...or from Git:
ansible-galaxy collection install git+https://github.com/gpa7407/ansible-dsp-platform.git
```

Install the Python libraries the modules need **on the target host** — either
directly:

```bash
pip3 install kubernetes cryptography PyYAML
```

...or as an Ansible play you run before `dsp_deploy` (recommended, so the whole
deploy is reproducible):

```yaml
- name: Install DSP deploy prerequisites
  hosts: dsp
  become: true
  tasks:
    - name: Install Python libraries for kubernetes.core + community.crypto
      ansible.builtin.pip:
        name:
          - kubernetes
          - cryptography
          - PyYAML
        # On distros with an externally-managed Python (PEP 668, e.g. Ubuntu
        # 24.04), either set this or install into a virtualenv:
        break_system_packages: true
```

> `break_system_packages` requires ansible-core >= 2.16. On older versions use
> `extra_args: --break-system-packages`, a virtualenv (`virtualenv: /opt/dsp-venv`),
> or the distro packages (e.g. `python3-kubernetes`, `python3-cryptography`).

## Usage

### Quick start

At minimum, point the role at your domain, the bundle, and your external
Keycloak/PostgreSQL:

```yaml
- name: Deploy Virtru DSP
  hosts: dsp
  become: true
  roles:
    - role: virtru.dsp_platform.dsp_deploy
      vars:
        dsp_domain: dsp.example.com
        dsp_tag: v2.8.0
        dsp_bundle_file: /opt/virtru-dsp-bundle-2.0.7.tar.gz
        dsp_db_host: postgres.example.com
        dsp_db_password: "{{ vault_db_password }}"
        dsp_keycloak_admin_password: "{{ vault_kc_admin_password }}"
```

See [`roles/dsp_deploy/README.md`](roles/dsp_deploy/README.md) and
[`roles/dsp_deploy/defaults/main.yml`](roles/dsp_deploy/defaults/main.yml) for the
full variable reference (registry, hostnames, realm/clients, timeouts, etc.).

### Full deployment example

This is an end-to-end deployment against an external Keycloak and PostgreSQL.

**1. Inventory** (`inventory.ini`) — the target is the host with cluster access
(e.g. a K3s node). Run the role there with a local connection:

```ini
[dsp]
dsp-node ansible_host=10.0.0.10 ansible_user=ubuntu
```

**2. Playbook** (`site.yml`):

```yaml
---
- name: Deploy the Virtru Data Security Platform
  hosts: dsp
  become: true
  gather_facts: true
  roles:
    - role: virtru.dsp_platform.dsp_deploy
      vars:
        # --- Core ---
        dsp_domain: dsp.example.com          # platform/keycloak/tagging hostnames derive from this
        dsp_tag: v2.8.0                        # DSP image tag (auto-detected from the bundle if omitted)
        dsp_bundle_file: /opt/virtru-dsp-bundle-2.0.7.tar.gz
        dsp_namespace: virtru

        # --- Container registry (bundle images are pushed here, chart pulls from here) ---
        dsp_registry_url: registry.example.com/virtru
        dsp_registry_insecure: false

        # --- External PostgreSQL (empty DB + full-privilege user) ---
        dsp_db_host: postgres.example.com
        dsp_db_name: opentdf
        dsp_db_user: opentdf
        dsp_db_password: "{{ vault_db_password }}"

        # --- External Keycloak (OIDC IdP) ---
        # dsp_keycloak_hostname defaults to keycloak.<dsp_domain>; override if different.
        dsp_keycloak_hostname: keycloak.example.com
        dsp_keycloak_admin_user: admin
        dsp_keycloak_admin_password: "{{ vault_kc_admin_password }}"
        dsp_keycloak_provision: true          # create the DSP realm/clients/roles (default)

        # --- Tools shipped in the bundle (optional; only if not on PATH) ---
        dsp_helm_bin: "/opt/virtru/tools-bin/helm"
        dsp_grpcurl_bin: "/opt/virtru/tools-bin/grpcurl"
```

**3. Run it:**

```bash
ansible-playbook -i inventory.ini site.yml
```

The role will, in order: extract the bundle + tools, push images to your
registry, generate KAS/cosign keys and Kubernetes secrets, generate the gateway
TLS cert, **provision the Keycloak realm/clients**, `helm upgrade --install` the
platform, apply the Traefik `IngressRoute`, and run health verification
(`/healthz`, well-known, gRPC health, Keycloak realm). On success the platform is
reachable at `https://platform.<dsp_domain>`.

> **Name resolution:** the platform pod must resolve your Keycloak hostname to
> reach the IdP at startup. In environments without shared DNS (e.g. a single-node
> lab), inject a host alias mapping the Keycloak hostname to the ingress IP:
>
> ```yaml
> dsp_extra_values:
>   platform:
>     hostAliases:
>       - ip: "10.0.0.10"          # the Traefik/ingress node IP
>         hostnames: ["keycloak.example.com"]
> ```

**Seed sample users** (test data with clearance attributes) by adding
`dsp_keycloak_seed_users: true`. **Bring your own realm** instead of provisioning
it by setting `dsp_keycloak_provision: false` and configuring the IdP yourself.

### Teardown

```yaml
- name: Teardown DSP
  virtru.dsp_platform.teardown:
    namespace: virtru
    remove_extract_dir: false
    remove_registry_images: false
```

### Composition with `virtru.dsp_tructl`

Post-deploy policy bootstrap (namespaces, attributes, mappings) belongs in
`virtru.dsp_tructl`:

```yaml
- import_role:
    name: virtru.dsp_platform.dsp_deploy
  vars:
    dsp_domain: dsp.example.com
    dsp_db_password: "{{ vault_db_password }}"
    dsp_keycloak_admin_password: "{{ vault_kc_admin_password }}"

- virtru.dsp_tructl.auth:
    state: login
    host: "https://platform.dsp.example.com"

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
