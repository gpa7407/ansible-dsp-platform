#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Virtru
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Ansible module for full DSP deployment on K3s."""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: deploy_k3s
short_description: Deploy Virtru DSP on a K3s cluster
description:
  - High-level module that performs a complete DSP deployment on K3s.
  - Handles bundle extraction, image push, key generation, secret creation,
    values.yaml generation, Helm install, Traefik ingress, and Keycloak provisioning.
  - Assumes K3s cluster is already installed and running.
  - Idempotent - each phase checks if work is already done before proceeding.
version_added: "1.0.0"
options:
  bundle_file:
    description:
      - Path to the DSP bundle tar.gz file.
      - Not required if the bundle is already extracted at C(extract_dir)/virtru-dsp-bundle.
    type: path
  domain:
    description: Base domain for the deployment (e.g., C(dsp.vm)).
    type: str
    required: true
  namespace:
    description: Kubernetes namespace for DSP.
    type: str
    default: virtru
  dsp_tag:
    description:
      - DSP version tag (e.g., C(v2.0.6.1)).
      - Auto-detected from the bundle if not specified.
    type: str
  registry_url:
    description: Container registry URL.
    type: str
    default: localhost:8888/virtru
  registry_insecure:
    description: Use HTTP instead of HTTPS for the registry.
    type: bool
    default: true
  platform_hostname:
    description: Platform hostname. Defaults to C(platform.{domain}).
    type: str
  keycloak_hostname:
    description: Keycloak hostname. Defaults to C(keycloak.{domain}).
    type: str
  tagging_hostname:
    description: Tagging PDP hostname. Defaults to C(tagging-pdp.{domain}).
    type: str
  db_password:
    description: PostgreSQL password for the opentdf user. Auto-generated if not specified.
    type: str
    no_log: true
  keycloak_admin_password:
    description: Keycloak admin password. Retrieved from K8s secret if not specified.
    type: str
    no_log: true
  keycloak_realm:
    description: Keycloak realm name.
    type: str
    default: opentdf
  deployment_mode:
    description: DSP deployment mode.
    type: str
    default: all
    choices: [all, core, kas]
  playground:
    description: Use embedded Keycloak and PostgreSQL.
    type: bool
    default: true
  extract_dir:
    description: Working directory for extracted bundle and tools.
    type: path
    default: /opt/virtru
  kas_key_size:
    description: RSA key size for KAS keys.
    type: int
    default: 2048
  host_aliases:
    description:
      - List of host alias dicts for cluster DNS resolution.
      - Each item should have C(ip) and C(hostnames) keys.
      - Auto-detected if not specified (uses first IP from hostname -I).
    type: list
    elements: dict
  additional_trusted_certs:
    description: Additional TLS certificate sources for the platform.
    type: list
    elements: dict
  cors_origins:
    description: CORS allowed origins.
    type: list
    elements: str
    default: ["*", "localhost:3000"]
  helm_timeout:
    description: Helm install timeout.
    type: str
    default: 15m
  keycloak_data_file:
    description:
      - Path to a custom keycloak_data.yaml file.
      - If not specified, the default from the bundle is used and updated.
    type: path
  keycloak_clients:
    description: Additional Keycloak clients to provision.
    type: list
    elements: dict
  keycloak_users:
    description: Additional Keycloak users to provision.
    type: list
    elements: dict
  wait:
    description: Wait for all pods to be ready after deployment.
    type: bool
    default: true
  mac_m4_host:
    description: Enable Mac M4 ARM workaround for Keycloak JVM.
    type: bool
    default: false
  cosign_password:
    description: Password for cosign key generation. Auto-generated if not specified.
    type: str
    no_log: true
  keycloak_statefulset_name:
    description: Name of the Keycloak StatefulSet in K8s.
    type: str
    default: platform-keycloak
  extra_helm_values:
    description: Additional Helm --set values as a dict.
    type: dict
    default: {}
notes:
  - Requires K3s cluster to be already installed and running.
  - Requires kubectl, openssl available on the target host.
  - The bundle_file must be accessible on the target host.
seealso:
  - module: virtru.dsp_platform.verify
  - module: virtru.dsp_platform.teardown
  - module: virtru.dsp_platform.bundle_extract
  - module: virtru.dsp_platform.copy_images
  - module: virtru.dsp_platform.helm_deploy
  - module: virtru.dsp_platform.keycloak_client
author:
  - Greg Paladin (@gpaladin)
'''

EXAMPLES = r'''
- name: Deploy DSP on K3s (minimal)
  virtru.dsp_platform.deploy_k3s:
    domain: dsp.vm
    bundle_file: /opt/virtru-dsp-bundle-v2.0.6.1.tar.gz

- name: Deploy DSP with custom settings
  virtru.dsp_platform.deploy_k3s:
    domain: dsp.vm
    bundle_file: /opt/bundle.tar.gz
    namespace: dsp-prod
    registry_url: registry.local:5000/virtru
    db_password: "{{ vault_db_password }}"
    keycloak_admin_password: "{{ vault_kc_password }}"
    mac_m4_host: true
    cors_origins:
      - "*"
      - "https://webadmin.dsp.vm"
'''

RETURN = r'''
changed:
  description: Whether any changes were made.
  type: bool
  returned: always
platform_url:
  description: The platform HTTPS URL.
  type: str
  returned: always
keycloak_url:
  description: The Keycloak HTTPS URL.
  type: str
  returned: always
dsp_bin:
  description: Path to the dsp CLI binary.
  type: str
  returned: always
tructl_bin:
  description: Path to the tructl CLI binary.
  type: str
  returned: always
helm_release:
  description: Helm release name.
  type: str
  returned: always
namespace:
  description: Kubernetes namespace used.
  type: str
  returned: always
dsp_tag:
  description: DSP version tag deployed.
  type: str
  returned: always
phases_completed:
  description: List of deployment phases that were executed.
  type: list
  returned: always
'''

import glob
import os
import secrets
import shutil
import string
import time

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.virtru.dsp_platform.plugins.module_utils.dsp_common import (
    DspRunner, version_ge, detect_architecture, find_tool_archive, extract_tool,
)
from ansible_collections.virtru.dsp_platform.plugins.module_utils.k8s_helper import K8sHelper
from ansible_collections.virtru.dsp_platform.plugins.module_utils.helm_helper import HelmHelper
from ansible_collections.virtru.dsp_platform.plugins.module_utils.keycloak_helper import KeycloakHelper
from ansible_collections.virtru.dsp_platform.plugins.module_utils.values_builder import ValuesBuilder


def generate_password(length=24):
    """Generate a random password."""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def phase_bundle(module, runner):
    """Phase 1: Extract bundle and tools."""
    bundle_file = module.params.get('bundle_file')
    extract_dir = module.params['extract_dir']
    tools_bin = os.path.join(extract_dir, 'tools-bin')

    # Check if already extracted
    dsp_bin = os.path.join(tools_bin, 'dsp')
    tructl_bin = os.path.join(tools_bin, 'tructl')
    helm_bin = os.path.join(tools_bin, 'helm')

    bundle_dir = None
    for candidate in [os.path.join(extract_dir, 'virtru-dsp-bundle'), extract_dir]:
        if os.path.isdir(os.path.join(candidate, 'charts')):
            bundle_dir = candidate
            break

    if bundle_dir and os.path.isfile(dsp_bin) and os.path.isfile(tructl_bin):
        return False, bundle_dir, tools_bin

    # If bundle is already extracted (synced) but tools aren't, just extract tools
    if bundle_dir and not os.path.isfile(dsp_bin):
        os.makedirs(tools_bin, exist_ok=True)
        # Skip tarball extraction, jump to tool extraction below
    elif bundle_file and os.path.isfile(bundle_file):
        # Extract from tarball
        import tarfile
        os.makedirs(extract_dir, exist_ok=True)
        os.makedirs(tools_bin, exist_ok=True)
        with tarfile.open(bundle_file, 'r:gz') as tar:
            tar.extractall(extract_dir)
    else:
        module.fail_json(msg="No bundle file or pre-extracted bundle found")

    # Locate bundle dir
    bundle_dir = extract_dir
    candidate = os.path.join(extract_dir, 'virtru-dsp-bundle')
    if os.path.isdir(os.path.join(candidate, 'charts')):
        bundle_dir = candidate

    # Extract tools
    arch = detect_architecture()

    dsp_tools_dir = os.path.join(bundle_dir, 'tools', 'dsp')
    if os.path.isdir(dsp_tools_dir):
        archive = find_tool_archive(dsp_tools_dir, 'data-security-platform', arch)
        if archive:
            extract_tool(archive, tools_bin, ['dsp', 'tructl'])

    helm_tools_dir = os.path.join(bundle_dir, 'tools', 'helm')
    if os.path.isdir(helm_tools_dir):
        archive = find_tool_archive(helm_tools_dir, 'helm', arch)
        if archive:
            extract_tool(archive, tools_bin, ['helm'])

    grpcurl_tools_dir = os.path.join(bundle_dir, 'tools', 'grpcurl')
    if os.path.isdir(grpcurl_tools_dir):
        archive = find_tool_archive(grpcurl_tools_dir, 'grpcurl', arch)
        if archive:
            extract_tool(archive, tools_bin, ['grpcurl'])

    return True, bundle_dir, tools_bin


def phase_images(module, runner, bundle_dir):
    """Phase 2: Push images to registry."""
    registry_url = module.params['registry_url']
    insecure = module.params['registry_insecure']

    marker_file = os.path.join(bundle_dir, '.images-pushed')
    if os.path.isfile(marker_file):
        return False

    cmd = [runner.dsp_bin, 'copy-images', registry_url]
    if insecure:
        cmd.append('--insecure')

    rc, stdout, stderr = runner.run_command(cmd, cwd=bundle_dir)

    with open(marker_file, 'w') as f:
        f.write(str(time.time()))

    return True


def phase_keys(module, runner, extract_dir, k8s):
    """Phase 3: Generate KAS RSA/ECC keys and cosign keys.

    Returns (changed, keys_dir, cosign_password). The cosign password is
    returned in memory only - never persisted to disk - and is then handed
    off to phase_secrets() which puts it into a K8s secret. The K8s secret
    is the only durable home for the password.

    If a cosign key is found on disk but the K8s secret holding the
    matching password is missing (e.g. namespace was torn down between
    runs), the keypair is regenerated since the original password is
    unrecoverable. A warning is emitted so the user knows old signatures
    will no longer verify.
    """
    keys_dir = os.path.join(extract_dir, 'keys')
    os.makedirs(keys_dir, exist_ok=True)

    changed = False
    kas_key_size = module.params['kas_key_size']

    # RSA key pair
    rsa_key = os.path.join(keys_dir, 'kas-private.pem')
    rsa_cert = os.path.join(keys_dir, 'kas-cert.pem')
    if not os.path.isfile(rsa_key):
        runner.run_command([
            'openssl', 'req', '-x509', '-nodes',
            '-newkey', 'RSA:{0}'.format(kas_key_size),
            '-subj', '/CN=kas',
            '-keyout', rsa_key,
            '-out', rsa_cert,
            '-days', '365',
        ])
        changed = True

    # ECC key pair
    ec_key = os.path.join(keys_dir, 'kas-ec-private.pem')
    ec_cert = os.path.join(keys_dir, 'kas-ec-cert.pem')
    if not os.path.isfile(ec_key):
        # Generate EC params and key in two steps (avoid process substitution)
        runner.run_command([
            'openssl', 'ecparam', '-name', 'prime256v1', '-genkey', '-out', ec_key,
        ])
        runner.run_command([
            'openssl', 'req', '-x509', '-new',
            '-key', ec_key,
            '-subj', '/CN=kas',
            '-out', ec_cert,
            '-days', '365',
        ])
        changed = True

    # Cosign keys
    cosign_dir = os.path.join(keys_dir, 'cosign')
    os.makedirs(cosign_dir, mode=0o700, exist_ok=True)
    cosign_key = os.path.join(cosign_dir, 'cosign.key')
    cosign_pub = os.path.join(cosign_dir, 'cosign.pub')
    cosign_pass_file = os.path.join(cosign_dir, 'cosign.pass')

    cosign_secret_exists = k8s.secret_exists('cosign-policyimportexport-keys')
    need_regen = not os.path.isfile(cosign_key) or not cosign_secret_exists

    cosign_password = None
    if need_regen:
        if os.path.isfile(cosign_key) and not cosign_secret_exists:
            module.warn(
                "Cosign keypair exists on disk but the K8s secret "
                "'cosign-policyimportexport-keys' is missing; regenerating. "
                "Any policy bundles signed by the previous key will fail "
                "signature verification."
            )
            for stale in (cosign_key, cosign_pub):
                if os.path.isfile(stale):
                    os.unlink(stale)

        cosign_password = module.params.get('cosign_password') or generate_password(16)

        # Pass COSIGN_PASSWORD via environ_update so the key is actually
        # encrypted; previously env_patch was built and discarded.
        runner.run_command(
            [runner.dsp_bin, 'cosign', 'generate-key-pair'],
            cwd=cosign_dir,
            environ_update={'COSIGN_PASSWORD': cosign_password},
        )
        changed = True

    # Remove any legacy cleartext password file (previous deploys may have
    # written it; the password now lives only in memory + K8s secret).
    if os.path.isfile(cosign_pass_file):
        try:
            os.unlink(cosign_pass_file)
        except OSError:
            pass

    return changed, keys_dir, cosign_password


def phase_secrets(module, runner, k8s, keys_dir, cosign_password=None):
    """Phase 4: Create K8s secrets.

    Args:
        cosign_password: In-memory cosign passphrase produced by phase_keys.
            Required when the cosign-policyimportexport-keys K8s secret
            doesn't yet exist; ignored otherwise (phase_keys ensures the
            keypair is regenerated whenever the secret is missing, so the
            password is always available when we need it).
    """
    namespace = module.params['namespace']
    db_password = module.params.get('db_password') or generate_password()
    changed = False

    # KAS private keys
    if not k8s.secret_exists('kas-private-keys'):
        k8s.create_secret_generic_idempotent('kas-private-keys', from_files={
            'kas-cert.pem': os.path.join(keys_dir, 'kas-cert.pem'),
            'kas-ec-cert.pem': os.path.join(keys_dir, 'kas-ec-cert.pem'),
            'kas-ec-private.pem': os.path.join(keys_dir, 'kas-ec-private.pem'),
            'kas-private.pem': os.path.join(keys_dir, 'kas-private.pem'),
        })
        changed = True

    # Cosign keys + passphrase. The passphrase is sourced from memory only -
    # it is never written to the host filesystem. K8s stores it in the
    # secret (in etcd) which is the only durable copy.
    cosign_dir = os.path.join(keys_dir, 'cosign')
    if not k8s.secret_exists('cosign-policyimportexport-keys'):
        if not cosign_password:
            module.fail_json(
                msg="Cannot create cosign K8s secret: passphrase not in memory. "
                    "phase_keys must regenerate the keypair to produce a fresh "
                    "passphrase. Delete {0} and re-run.".format(cosign_dir),
            )

        from_files = {
            'cosign.key': os.path.join(cosign_dir, 'cosign.key'),
            'cosign.pub': os.path.join(cosign_dir, 'cosign.pub'),
        }
        literals = {'cosign.pass': cosign_password}
        k8s.create_secret_generic_idempotent(
            'cosign-policyimportexport-keys',
            literals=literals,
            from_files=from_files,
        )
        changed = True

    # Database credentials — the chart references this secret in volume mounts.
    # Must exist before helm install regardless of playground mode.
    if not k8s.secret_exists('opentdf-db-credentials'):
        k8s.create_secret_generic_idempotent('opentdf-db-credentials', literals={
            'password': db_password,
        })
        changed = True

    # Encrypted search key
    if not k8s.secret_exists('dsp-enc-search-key'):
        # Generate random 32-byte hex key
        enc_key = secrets.token_hex(32)
        k8s.create_secret_generic_idempotent('dsp-enc-search-key', literals={
            'encrypted-search-key': enc_key,
        })
        changed = True

    return changed, db_password


def phase_values(module, runner, bundle_dir, dsp_tag):
    """Phase 5: Generate values.yaml by patching the stock values from the bundle.

    Uses sed for registry/domain replacements and yq for structured YAML mutations,
    mirroring the proven approach from provision-values.sh.
    """
    import shutil

    domain = module.params['domain']
    namespace = module.params['namespace']
    registry_url = module.params['registry_url']
    registry_fqdn = registry_url.split('/')[0] if '/' in registry_url else registry_url
    playground = module.params['playground']
    keycloak_realm = module.params['keycloak_realm']

    platform_hostname = module.params.get('platform_hostname') or 'platform.{0}'.format(domain)
    keycloak_hostname = module.params.get('keycloak_hostname') or 'keycloak.{0}'.format(domain)
    tagging_hostname = module.params.get('tagging_hostname') or 'tagging-pdp.{0}'.format(domain)
    auth_url = 'https://{0}'.format(keycloak_hostname)
    platform_url = 'https://{0}'.format(platform_hostname)

    values_path = os.path.join(bundle_dir, 'values.yaml')
    stock_values = os.path.join(bundle_dir, 'kubernetes', 'values.yaml')

    if os.path.isfile(values_path):
        return False, values_path, platform_hostname, keycloak_hostname, tagging_hostname

    # Copy stock values.yaml as starting point
    if not os.path.isfile(stock_values):
        module.fail_json(msg="Stock values.yaml not found at {0}".format(stock_values))

    shutil.copy2(stock_values, values_path)

    # Also copy tagging workflows
    stock_tagging = os.path.join(bundle_dir, 'kubernetes', 'tagging-pdp-workflows.yaml')
    tagging_path = os.path.join(bundle_dir, 'tagging-pdp-workflows.yaml')
    if os.path.isfile(stock_tagging) and not os.path.isfile(tagging_path):
        shutil.copy2(stock_tagging, tagging_path)

    # Phase 5a: sed replacements for registry and domain
    runner.run_command([
        'sed', '-i',
        '-e', 's@docker.io@{0}@g'.format(registry_fqdn),
        '-e', 's@example.com@{0}@g'.format(domain),
        values_path,
    ])

    # Phase 5b: yq mutations (install yq if needed)
    yq_bin = shutil.which('yq')
    if not yq_bin:
        # Try to use yq from tools or install it
        module.warn("yq not found, attempting structured YAML edits with sed fallback")
        # Critical sed-based fallback for the most important settings
        sed_replacements = [
            ('s/playground: true/playground: {0}/g'.format(str(playground).lower()), values_path),
        ]
        for pattern, target in sed_replacements:
            runner.run_command(['sed', '-i', pattern, target])
    else:
        # Full yq-based patching (mirrors provision-values.sh)
        yq_edits = [
            # Image tag
            '.platform.image.tag = "{0}"'.format(dsp_tag),
            # Playground mode
            '.platform.playground = {0}'.format(str(playground).lower()),
            # Ingress
            '.platform.ingress.enabled = true',
            '.platform.keycloak.ingress.enabled = false',
            # Keycloak config CLI - disable (we provision via tructl)
            '.platform.keycloak.keycloakConfigCli.enabled = false',
            # Keycloak health
            '.platform.keycloak.extraEnv = .platform.keycloak.extraEnv // [] | '
            '.platform.keycloak.extraEnv += [{"name": "KC_HEALTH_ENABLED", "value": "true"}]',
            # CORS
            '.platform.server.cors = {"enabled": true, "allowedorigins": ["*", "localhost:3000"]}',
            # Services
            '.platform.services.dsp_services.tdfviewer.enabled = false',
            '.platform.services.dsp_services.outlook.enabled = false',
            '.platform.services.dsp_services.sharepoint.enabled = false',
            '.platform.services.policyimportexport.enabled = true',
            '.platform.services.policyimportexport.privatesignkey = "dsp-keys/policyimportexport/cosign.key"',
            '.platform.services.policyimportexport.privatesignkeypassphrasepath = "dsp-keys/policyimportexport/cosign.pass"',
            '.platform.services.policyimportexport.truststore = "dsp-keys/policyimportexport"',
            # Database host — only override for non-playground mode
            # In playground mode the chart sets this to the embedded PostgreSQL service name
            # TLS trusted certs
            '.platform.server.tls.additionalTrustedCerts[0] = {"secret": {"name": "dsp-gateway-tls", "items": [{"key": "tls.crt", "path": "platform.crt"}]}}',
        ]

        for expr in yq_edits:
            runner.run_command([yq_bin, 'eval', expr, '-i', values_path])

        # Host aliases for cluster DNS
        host_aliases = module.params.get('host_aliases')
        if not host_aliases:
            rc, stdout, _ = runner.run_command(['hostname', '-I'], check_rc=False)
            if rc == 0 and stdout.strip():
                ip = stdout.strip().split()[0]
                runner.run_command([yq_bin, 'eval',
                    '.platform.hostAliases[0] = {{"ip": "{0}", "hostnames": ["{1}"]}}'.format(
                        ip, keycloak_hostname),
                    '-i', values_path])
                runner.run_command([yq_bin, 'eval',
                    '.taggingPDP.hostAliases[0] = {{"ip": "{0}", "hostnames": ["{1}"]}}'.format(
                        ip, keycloak_hostname),
                    '-i', values_path])

        # Auth endpoints (set values, yq handles anchors from stock file)
        runner.run_command([yq_bin, 'eval',
            '.authEndpoint = "{0}"'.format(auth_url), '-i', values_path])
        runner.run_command([yq_bin, 'eval',
            '.issuer = "{0}/realms/{1}"'.format(auth_url, keycloak_realm), '-i', values_path])
        runner.run_command([yq_bin, 'eval',
            '.tokenEndpoint = "{0}/realms/{1}/protocol/openid-connect/token"'.format(
                auth_url, keycloak_realm), '-i', values_path])

        # v2.6+ specific changes
        if version_ge(dsp_tag, 'v2.6'):
            v26_edits = [
                '.platform.enable_pprof = true',
                '.platform.http.readTimeout = "30s"',
                '.platform.http.writeTimeout = "30s"',
                # Keycloak subchart image overrides
                '.platform.keycloak.image.registry = "{0}"'.format(registry_fqdn),
                '.platform.keycloak.image.repository = "virtru/keycloak"',
                '.platform.keycloak.keycloakConfigCli.image.registry = "{0}"'.format(registry_fqdn),
                '.platform.keycloak.keycloakConfigCli.image.repository = "virtru/keycloak-config-cli"',
                # PostgreSQL subchart image overrides
                '.platform.postgresql.image.registry = "{0}"'.format(registry_fqdn),
                '.platform.postgresql.image.repository = "virtru/postgresql"',
                '.platform.postgresql.volumePermissions.image.registry = "{0}"'.format(registry_fqdn),
                '.platform.postgresql.volumePermissions.image.repository = "virtru/os-shell"',
            ]
            # DB credentials secret reference
            v26_edits.extend([
                '.platform.db.password.secret.name = "opentdf-db-credentials"',
                '.platform.db.password.secret.key = "password"',
            ])

            for expr in v26_edits:
                runner.run_command([yq_bin, 'eval', expr, '-i', values_path])

    # Update keycloak_data.yaml
    kc_data_file = os.path.join(bundle_dir, 'samples', 'keycloak_data.yaml')
    if os.path.isfile(kc_data_file) and yq_bin:
        runner.run_command([yq_bin, 'eval',
            '.baseUrl = "{0}"'.format(auth_url), '-i', kc_data_file])
        runner.run_command([yq_bin, 'eval',
            '.serverBaseUrl = "{0}"'.format(platform_url), '-i', kc_data_file])
        runner.run_command([yq_bin, 'eval',
            '.redirectUris = ["{0}/*", "{1}/*"]'.format(platform_url, auth_url),
            '-i', kc_data_file])

        if version_ge(dsp_tag, 'v2.6'):
            for expr in [
                '.realms[0].custom_realm_roles // [] += [{"name": "dsp-org-admin"}]',
                '.realms[0].custom_realm_roles // [] += [{"name": "dsp-admin"}]',
                '.realms[0].custom_realm_roles // [] += [{"name": "dsp-standard"}]',
            ]:
                runner.run_command([yq_bin, 'eval', expr, '-i', kc_data_file])

    return True, values_path, platform_hostname, keycloak_hostname, tagging_hostname


def phase_tls(module, runner, k8s, extract_dir, platform_hostname, keycloak_hostname):
    """Phase 6: Generate TLS certs for Traefik ingress."""
    certs_dir = os.path.join(extract_dir, 'certs')
    os.makedirs(certs_dir, exist_ok=True)

    changed = False

    # Generate platform cert
    key_file = os.path.join(certs_dir, '{0}.key'.format(platform_hostname))
    cert_file = os.path.join(certs_dir, '{0}.pem'.format(platform_hostname))

    if not os.path.isfile(key_file):
        # Generate cert with SANs for all hostnames
        runner.run_command([
            'openssl', 'req', '-x509', '-nodes',
            '-newkey', 'RSA:2048',
            '-subj', '/CN={0}'.format(platform_hostname),
            '-addext', 'subjectAltName=DNS:{0},DNS:{1},DNS:*.{2}'.format(
                platform_hostname, keycloak_hostname, module.params['domain']
            ),
            '-keyout', key_file,
            '-out', cert_file,
            '-days', '365',
        ])
        changed = True

    # Create TLS secret
    if k8s.create_tls_secret('dsp-gateway-tls', cert_file, key_file):
        changed = True

    return changed


def phase_helm(module, runner, helm, bundle_dir, values_path, dsp_tag):
    """Phase 7: Helm upgrade --install."""
    namespace = module.params['namespace']
    helm_timeout = module.params['helm_timeout']

    # Find chart
    chart_matches = glob.glob(os.path.join(bundle_dir, 'charts', 'data-security-platform-*.tgz'))
    if not chart_matches:
        module.fail_json(msg="No DSP Helm chart found in {0}/charts/".format(bundle_dir))
    chart_path = chart_matches[0]

    # Find tagging workflows file
    tagging_values = os.path.join(bundle_dir, 'tagging-pdp-workflows.yaml')
    values_files = [values_path]
    if os.path.isfile(tagging_values):
        values_files.append(tagging_values)

    # Extra --set values for Mac M4
    set_values = {}
    if module.params['mac_m4_host']:
        set_values['platform.keycloak.extraEnvVars[0].name'] = 'JAVA_TOOL_OPTIONS'
        set_values['platform.keycloak.extraEnvVars[0].value'] = '-XX:UseSVE=0'
        set_values['platform.keycloak.keycloakConfigCli.extraEnvVars[0].name'] = 'JAVA_TOOL_OPTIONS'
        set_values['platform.keycloak.keycloakConfigCli.extraEnvVars[0].value'] = '-XX:UseSVE=0'

    # Merge user extra values
    extra = module.params.get('extra_helm_values') or {}
    set_values.update(extra)

    helm.upgrade_install(
        release_name='dsp',
        chart=chart_path,
        values_files=values_files,
        set_values=set_values if set_values else None,
        timeout=helm_timeout,
        wait=False,  # We handle waiting ourselves
        debug=True,
    )

    # Handle v2.5.3 scale-down for Keycloak provisioning
    if dsp_tag == 'v2.5.3':
        # Wait for pods to be created
        time.sleep(10)
        k8s = K8sHelper(runner, namespace)
        k8s.scale_deployment('tagging-pdp', 0)
        k8s.scale_deployment('dsp-platform', 0)

    return True


def phase_ingress(module, runner, k8s, dsp_tag, platform_hostname, keycloak_hostname,
                  tagging_hostname, extract_dir):
    """Phase 8: Create Traefik IngressRoutes (K3s-specific)."""
    namespace = module.params['namespace']
    kc_statefulset = module.params['keycloak_statefulset_name']

    # Determine tagging service name based on version
    tagging_service = 'tagging-pdp' if dsp_tag == 'v2.5.3' else 'dsp-platform'

    manifest = """apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: dsp-all
  namespace: {namespace}
spec:
  entryPoints:
  - websecure
  routes:
  - kind: Rule
    match: Host("{platform}")
    services:
    - name: dsp-platform
      namespace: {namespace}
      passHostHeader: true
      port: 9000
      scheme: h2c
  - kind: Rule
    match: Host("{tagging}")
    services:
    - name: {tagging_svc}
      namespace: {namespace}
      passHostHeader: true
      port: 9000
      scheme: h2c
  - kind: Rule
    match: Host("{keycloak}")
    services:
    - name: {kc_ss}
      namespace: {namespace}
      passHostHeader: true
      port: 80
      scheme: http
  - kind: Rule
    match: Host("{keycloak}") && PathPrefix("/health/")
    services:
    - name: {kc_ss}
      namespace: {namespace}
      passHostHeader: true
      port: 9000
      scheme: http
  tls:
    secretName: dsp-gateway-tls
""".format(
        namespace=namespace,
        platform=platform_hostname,
        tagging=tagging_hostname,
        keycloak=keycloak_hostname,
        tagging_svc=tagging_service,
        kc_ss=kc_statefulset,
    )

    k8s.apply_manifest(manifest)

    # Wait for endpoint to respond
    for attempt in range(30):
        rc, stdout, _ = runner.run_command(
            ['curl', '-k', '-s', '-o', '/dev/null', '-w', '%{http_code}',
             'https://{0}/healthz'.format(platform_hostname)],
            check_rc=False,
        )
        if rc == 0 and stdout.strip() in ('200', '426'):
            break
        time.sleep(6)

    return True


def phase_keycloak(module, runner, k8s, kc_helper, bundle_dir, dsp_tag,
                   keycloak_hostname):
    """Phase 9: Provision Keycloak realm and clients."""
    namespace = module.params['namespace']
    kc_statefulset = module.params['keycloak_statefulset_name']

    # Wait for Keycloak to be ready
    k8s.wait_for_rollout('statefulset', kc_statefulset, timeout='15m')

    # Get admin password
    kc_password = module.params.get('keycloak_admin_password')
    if not kc_password:
        kc_password = k8s.get_secret_value(kc_statefulset, 'admin-password')
        if not kc_password:
            module.fail_json(msg="Could not determine Keycloak admin password")

    # Determine keycloak data file
    kc_data_file = module.params.get('keycloak_data_file')
    if not kc_data_file:
        kc_data_file = os.path.join(bundle_dir, 'samples', 'keycloak_data.yaml')

    if not os.path.isfile(kc_data_file):
        module.fail_json(msg="Keycloak data file not found: {0}".format(kc_data_file))

    # Update keycloak_data.yaml with correct URLs
    try:
        import yaml
        with open(kc_data_file, 'r') as f:
            kc_data = yaml.safe_load(f)

        auth_url = 'https://{0}'.format(keycloak_hostname)
        platform_url = 'https://platform.{0}'.format(module.params['domain'])

        kc_data['baseUrl'] = auth_url
        kc_data['serverBaseUrl'] = platform_url
        kc_data['redirectUris'] = [
            '{0}/*'.format(platform_url),
            '{0}/*'.format(auth_url),
        ]

        # Add v2.6+ realm roles
        if version_ge(dsp_tag, 'v2.6') and 'realms' in kc_data:
            realm = kc_data['realms'][0]
            existing_roles = [r.get('name') for r in realm.get('custom_realm_roles', [])]
            for role_name in ['dsp-org-admin', 'dsp-admin', 'dsp-standard']:
                if role_name not in existing_roles:
                    realm.setdefault('custom_realm_roles', []).append({'name': role_name})

            # Add role assignments to service accounts
            clients = realm.get('clients', [])
            if len(clients) > 0:
                clients[0].setdefault('sa_realm_roles', [])
                if 'dsp-org-admin' not in clients[0]['sa_realm_roles']:
                    clients[0]['sa_realm_roles'].append('dsp-org-admin')
            if len(clients) > 1:
                clients[1].setdefault('sa_realm_roles', [])
                if 'dsp-admin' not in clients[1]['sa_realm_roles']:
                    clients[1]['sa_realm_roles'].append('dsp-admin')

            # Add role to users
            for user in realm.get('users', []):
                user.setdefault('realmRoles', [])
                if 'dsp-standard' not in user['realmRoles']:
                    user['realmRoles'].append('dsp-standard')

        with open(kc_data_file, 'w') as f:
            yaml.dump(kc_data, f, default_flow_style=False, sort_keys=False)
    except ImportError:
        pass  # If PyYAML not available, use file as-is
    except Exception:
        pass  # Non-fatal: provisioning may still work with original file

    # Run keycloak-from-config
    # The "management permissions" error at the end is a known Keycloak issue
    # and is non-fatal — all realm, clients, roles, and users are created before it.
    kc_endpoint = 'https://{0}/'.format(keycloak_hostname)
    cmd = [runner.dsp_bin, 'tructl', 'provision', 'keycloak-from-config',
           '-f', kc_data_file,
           '-e', kc_endpoint,
           '--username', 'admin',
           '--password', kc_password]
    rc, stdout, stderr = runner.run_command(cmd, check_rc=False)
    if rc != 0:
        # Check if this is the known management permissions error
        if 'management permissions' in stderr.lower() or 'management permissions' in stdout.lower():
            module.warn("Keycloak provisioning completed with non-fatal 'management permissions' error")
        else:
            runner.module.fail_json(
                msg="Keycloak provisioning failed",
                cmd=' '.join(cmd), rc=rc, stdout=stdout, stderr=stderr,
                phases_completed=runner.phases_completed,
            )

    # For v2.5.3, scale back up after provisioning
    if dsp_tag == 'v2.5.3':
        k8s.scale_deployment('dsp-platform', 1)
        k8s.wait_for_rollout('deployment', 'dsp-platform', timeout='10m')
        k8s.scale_deployment('tagging-pdp', 1)
        k8s.wait_for_rollout('deployment', 'tagging-pdp', timeout='10m')
    else:
        k8s.wait_for_rollout('deployment', 'dsp-platform', timeout='10m')

    return True


def phase_healthcheck(module, runner, platform_hostname):
    """Final health check."""
    # Check platform health
    for attempt in range(10):
        rc, stdout, _ = runner.run_command(
            ['curl', '-k', '-s', 'https://{0}/healthz'.format(platform_hostname)],
            check_rc=False,
        )
        if rc == 0 and 'SERVING' in stdout:
            return True
        time.sleep(5)

    module.fail_json(msg="Platform health check failed after deployment")
    return False


def main():
    module = AnsibleModule(
        argument_spec=dict(
            bundle_file=dict(type='path'),
            domain=dict(type='str', required=True),
            namespace=dict(type='str', default='virtru'),
            dsp_tag=dict(type='str'),
            registry_url=dict(type='str', default='localhost:8888/virtru'),
            registry_insecure=dict(type='bool', default=True),
            platform_hostname=dict(type='str'),
            keycloak_hostname=dict(type='str'),
            tagging_hostname=dict(type='str'),
            db_password=dict(type='str', no_log=True),
            keycloak_admin_password=dict(type='str', no_log=True),
            keycloak_realm=dict(type='str', default='opentdf'),
            deployment_mode=dict(type='str', default='all', choices=['all', 'core', 'kas']),
            playground=dict(type='bool', default=True),
            extract_dir=dict(type='path', default='/opt/virtru'),
            kas_key_size=dict(type='int', default=2048),
            host_aliases=dict(type='list', elements='dict'),
            additional_trusted_certs=dict(type='list', elements='dict'),
            cors_origins=dict(type='list', elements='str', default=['*', 'localhost:3000']),
            helm_timeout=dict(type='str', default='15m'),
            keycloak_data_file=dict(type='path'),
            keycloak_clients=dict(type='list', elements='dict'),
            keycloak_users=dict(type='list', elements='dict'),
            wait=dict(type='bool', default=True),
            mac_m4_host=dict(type='bool', default=False),
            cosign_password=dict(type='str', no_log=True),
            keycloak_statefulset_name=dict(type='str', default='platform-keycloak'),
            extra_helm_values=dict(type='dict', default={}),
        ),
        supports_check_mode=True,
    )

    if module.check_mode:
        module.exit_json(changed=True, msg="Would deploy DSP on K3s")

    # Validate
    bundle_file = module.params.get('bundle_file')
    extract_dir = module.params['extract_dir']
    pre_extracted = os.path.isdir(os.path.join(extract_dir, 'virtru-dsp-bundle', 'charts'))

    if not bundle_file and not pre_extracted:
        module.fail_json(
            msg="Either bundle_file must be provided or a pre-extracted bundle "
                "must exist at {0}/virtru-dsp-bundle/".format(extract_dir)
        )
    if bundle_file and not os.path.isfile(bundle_file) and not pre_extracted:
        module.fail_json(msg="Bundle file not found: {0}".format(bundle_file))

    # Initialize runner with placeholder paths (updated after bundle extraction)
    runner = DspRunner(module)
    overall_changed = False

    # Phase 1: Bundle extraction
    changed, bundle_dir, tools_bin = phase_bundle(module, runner)
    overall_changed = overall_changed or changed
    runner.log_phase('bundle')

    # Update runner with actual tool paths
    runner.dsp_bin = os.path.join(tools_bin, 'dsp')
    runner.tructl_bin = os.path.join(tools_bin, 'tructl')
    runner.helm_bin = os.path.join(tools_bin, 'helm')

    # Detect DSP tag
    dsp_tag = module.params.get('dsp_tag')
    if not dsp_tag:
        chart_matches = glob.glob(os.path.join(bundle_dir, 'charts', 'data-security-platform-*.tgz'))
        if chart_matches:
            basename = os.path.basename(chart_matches[0])
            version_part = basename.replace('data-security-platform-', '').replace('.tgz', '')
            dsp_tag = 'v{0}'.format(version_part)
        else:
            module.fail_json(msg="Could not detect DSP version from bundle")

    # Initialize helpers
    namespace = module.params['namespace']
    k8s = K8sHelper(runner, namespace)
    helm = HelmHelper(runner, namespace)

    # Ensure namespace
    k8s.ensure_namespace()

    # Phase 2: Push images
    changed = phase_images(module, runner, bundle_dir)
    overall_changed = overall_changed or changed
    runner.log_phase('images')

    # Phase 3: Generate keys (cosign password stays in memory only)
    changed, keys_dir, cosign_password = phase_keys(
        module, runner, module.params['extract_dir'], k8s,
    )
    overall_changed = overall_changed or changed
    runner.log_phase('keys')

    # Phase 4: Create secrets
    changed, db_password = phase_secrets(
        module, runner, k8s, keys_dir, cosign_password=cosign_password,
    )
    overall_changed = overall_changed or changed
    runner.log_phase('secrets')

    # Phase 5: Generate values.yaml
    changed, values_path, platform_host, kc_host, tagging_host = phase_values(
        module, runner, bundle_dir, dsp_tag
    )
    overall_changed = overall_changed or changed
    runner.log_phase('values')

    # Phase 6: TLS certs
    changed = phase_tls(module, runner, k8s, module.params['extract_dir'],
                        platform_host, kc_host)
    overall_changed = overall_changed or changed
    runner.log_phase('tls')

    # Phase 7: Helm install
    if not helm.release_exists('dsp'):
        phase_helm(module, runner, helm, bundle_dir, values_path, dsp_tag)
        overall_changed = True
    runner.log_phase('helm')

    # Phase 8: Traefik IngressRoute
    if not k8s.resource_exists('ingressroute', 'dsp-all'):
        phase_ingress(module, runner, k8s, dsp_tag, platform_host, kc_host,
                      tagging_host, module.params['extract_dir'])
        overall_changed = True
    runner.log_phase('ingress')

    # Phase 9: Keycloak provisioning
    phase_keycloak(module, runner, k8s, None, bundle_dir, dsp_tag, kc_host)
    overall_changed = True
    runner.log_phase('keycloak')

    # Final health check
    if module.params['wait']:
        phase_healthcheck(module, runner, platform_host)
        runner.log_phase('healthcheck')

    module.exit_json(
        changed=overall_changed,
        platform_url='https://{0}'.format(platform_host),
        keycloak_url='https://{0}'.format(kc_host),
        dsp_bin=runner.dsp_bin,
        tructl_bin=runner.tructl_bin,
        helm_release='dsp',
        namespace=namespace,
        dsp_tag=dsp_tag,
        phases_completed=runner.phases_completed,
    )


if __name__ == '__main__':
    main()
