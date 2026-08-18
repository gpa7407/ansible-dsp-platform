# `virtru.dsp_platform.dsp_deploy`

Deploy the Virtru Data Security Platform (DSP) onto an existing
K3s/Kubernetes cluster.

This role replaces the monolithic `deploy_k3s` module. Instead of one 1000-line
Python module that shelled out to `sed`/`yq`/`kubectl`/`helm`, the deployment is
now a sequence of small, idiomatic tasks that render Jinja2 templates and apply
them with the `kubernetes.core` modules.

## What it does (phase → file)

| Phase | File | Tooling |
|-------|------|---------|
| Preflight + namespace | `preflight.yml` | `kubernetes.core.k8s` |
| Extract bundle + tools | `bundle.yml` | `virtru.dsp_platform.bundle_extract` |
| Push images to registry | `images.yml` | `virtru.dsp_platform.copy_images` |
| KAS + cosign keys | `keys.yml` | `community.crypto`, `dsp cosign` |
| K8s secrets | `secrets.yml` | `kubernetes.core.k8s` |
| Gateway TLS + `values.yaml` | `values.yml` | `community.crypto`, `template` |
| Helm install | `deploy.yml` | `kubernetes.core.helm` |
| Traefik IngressRoute | `ingress.yml` | `kubernetes.core.k8s` (template) |
| Keycloak realm provisioning | `keycloak.yml` | `community.general.keycloak_*` |
| Health verification | `verify.yml` | `virtru.dsp_platform.verify` |

The rendered `values.yaml` comes from `templates/values.yaml.j2` — a readable,
diffable file that preserves the chart's YAML anchors so a single edit
propagates to every alias. The image tag (absent from the bundle's stock
values, which is what silently pinned older deploys to the chart-default tag)
is set explicitly.

## Requirements

- An existing K3s/Kubernetes cluster; `dsp_kubeconfig` readable by the run user.
- Collections: `kubernetes.core`, `community.crypto`, `community.general`.
- Target Python libraries: `kubernetes` (for `k8s`/`k8s_info`), `cryptography`
  (for `community.crypto`), `PyYAML`.
- The `helm` binary (the DSP bundle ships one; `dsp_helm_bin` points at it).

## External Keycloak + PostgreSQL (required)

DSP requires an **external, operational OIDC IdP and PostgreSQL database** —
embedded "playground" mode is not supported by this role. Per the DSP docs, the
IdP must be any OIDC-compliant provider and the database **PostgreSQL 15+**
(reference deployments use Keycloak 25 / PostgreSQL 16).

Point the role at your running services:

- Database: `dsp_db_host`, `dsp_db_port`, `dsp_db_name`, `dsp_db_user`,
  `dsp_db_password` (a dedicated empty DB with a full-privilege user).
- Keycloak: `dsp_keycloak_hostname` (→ `dsp_auth_url`) pointing at your IdP.

### Realm provisioning

The role provisions the DSP realm natively with the `community.general.keycloak_*`
modules (`dsp_keycloak_provision: true`, the default) — realm, roles, clients
(each with the shared audience mapper), and service-account role mappings,
including the `realm-management` roles the entity-resolution service needs.
This runs **before** the Helm deploy, because the platform discovers the realm's
OIDC well-known at startup.

DSP **2.0.7 removed `tructl provision`**, so this native path replaces it and
requires `dsp_keycloak_admin_password`. Customize `dsp_keycloak_clients` /
`dsp_keycloak_realm_roles` to change what's created; set `dsp_keycloak_provision:
false` if you manage the realm out-of-band. Sample users (with clearance
attributes) are created only when `dsp_keycloak_seed_users: true`.

Validated reference: DSP 2.0.7 (v2.8.0) against **Keycloak 26.7** and
**PostgreSQL 18**.

## Example

```yaml
- hosts: dsp
  become: true
  roles:
    - role: virtru.dsp_platform.dsp_deploy
      vars:
        dsp_domain: dsp.vm
        dsp_tag: v2.8.0
        dsp_bundle_file: /home/vagrant/virtru-dsp-bundle-2.0.7.tar.gz
        # external IdP/DB (2.0.7 default)
        dsp_keycloak_hostname: keycloak.corp.example
        dsp_db_host: postgres.corp.example
        dsp_db_password: "{{ vault_db_password }}"
```

See `defaults/main.yml` for the full list of variables (all prefixed `dsp_`).
