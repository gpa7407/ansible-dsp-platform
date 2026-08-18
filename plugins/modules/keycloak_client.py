#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Virtru
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Ansible module for managing Keycloak clients on a DSP-embedded Keycloak."""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: keycloak_client
short_description: Manage Keycloak clients on the DSP-embedded Keycloak
description:
  - Creates, updates, and deletes Keycloak clients on the Keycloak instance
    deployed alongside DSP.
  - Talks to Keycloak via C(kcadm.sh) executed inside the Keycloak pod with
    C(kubectl exec). This is the air-gapped-friendly path that doesn't require
    the Keycloak admin endpoint to be exposed to the Ansible controller.
  - Idempotent - existing clients are updated in place; missing clients are
    created; clients in state C(absent) are deleted only if present.
  - Returns the client secret on creation or when C(regenerate_secret) is true.
version_added: "1.0.0"
options:
  realm:
    description: Keycloak realm name.
    type: str
    required: true
  state:
    description:
      - C(present) ensures the client exists with the configured attributes.
      - C(absent) deletes the client if it exists.
    type: str
    choices: [present, absent]
    default: present
  client_id:
    description: Keycloak clientId (the human-readable identifier).
    type: str
    required: true
  name:
    description: Display name.
    type: str
  description:
    description: Free-text description.
    type: str
  enabled:
    description: Whether the client is enabled.
    type: bool
    default: true
  public_client:
    description: If true, the client is public (no secret).
    type: bool
    default: false
  client_authenticator_type:
    description: Client authentication method (e.g. C(client-secret), C(client-jwt)).
    type: str
    default: client-secret
  standard_flow_enabled:
    description: Enable OAuth 2.0 authorization-code flow.
    type: bool
    default: true
  direct_access_grants_enabled:
    description: Enable OAuth 2.0 resource-owner password credentials flow.
    type: bool
    default: true
  implicit_flow_enabled:
    description: Enable OAuth 2.0 implicit flow.
    type: bool
    default: false
  service_accounts_enabled:
    description: Enable service-account flow (client_credentials grant).
    type: bool
    default: false
  secret:
    description:
      - Explicit client secret value.
      - Only meaningful for confidential clients (C(public_client=false)).
      - Use C(no_log) when supplying via inventory.
    type: str
  redirect_uris:
    description: List of allowed redirect URIs.
    type: list
    elements: str
  web_origins:
    description: List of allowed CORS origins.
    type: list
    elements: str
  protocol:
    description: Protocol (C(openid-connect) or C(saml)).
    type: str
    default: openid-connect
  attributes:
    description:
      - Free-form client attributes dict.
      - "Example: C({access.token.lifespan: '900'})."
    type: dict
  service_account_realm_roles:
    description:
      - List of realm role names to assign to the client's service-account user.
      - Requires C(service_accounts_enabled=true).
    type: list
    elements: str
  regenerate_secret:
    description:
      - Force secret rotation even if the client already exists.
      - The new secret is returned in the C(secret) field of the result.
    type: bool
    default: false
  namespace:
    description: Kubernetes namespace where Keycloak runs.
    type: str
    default: virtru
  keycloak_statefulset_name:
    description: Name of the Keycloak StatefulSet (used to find the pod and admin password).
    type: str
    default: platform-keycloak
  admin_user:
    description: Keycloak admin username.
    type: str
    default: admin
  admin_password:
    description:
      - Keycloak admin password.
      - Auto-fetched from the Keycloak K8s secret if not provided.
    type: str
    no_log: true
  kubectl_bin:
    description: Path to kubectl.
    type: path
    default: kubectl
notes:
  - kcadm.sh inside the pod talks to C(http://localhost:8080) - the pod-local
    Keycloak endpoint - so no network reachability to the public hostname is
    needed from the Ansible controller.
seealso:
  - description: The dsp_deploy role provisions the initial Keycloak realm and clients.
    link: https://github.com/gpa7407/ansible-dsp-platform/tree/main/roles/dsp_deploy
author:
  - Greg Paladin (@gpaladin)
'''

EXAMPLES = r'''
- name: Create a confidential service-account client
  virtru.dsp_platform.keycloak_client:
    realm: opentdf
    client_id: my-service
    service_accounts_enabled: true
    standard_flow_enabled: false
    direct_access_grants_enabled: false
    service_account_realm_roles:
      - dsp-admin
  register: kc_client
  no_log: true   # the result includes the client secret

- name: Update redirect URIs on an existing client
  virtru.dsp_platform.keycloak_client:
    realm: opentdf
    client_id: web-app
    redirect_uris:
      - https://app.dsp.vm/*
      - http://localhost:3000/*
    web_origins:
      - https://app.dsp.vm
      - http://localhost:3000

- name: Rotate a client secret
  virtru.dsp_platform.keycloak_client:
    realm: opentdf
    client_id: my-service
    regenerate_secret: true
  register: rotated

- name: Delete a client
  virtru.dsp_platform.keycloak_client:
    realm: opentdf
    client_id: deprecated-client
    state: absent
'''

RETURN = r'''
changed:
  description: Whether the client was created, updated, deleted, or had its secret rotated.
  type: bool
  returned: always
client_id:
  description: The clientId managed.
  type: str
  returned: always
client_uuid:
  description: Keycloak's internal UUID for the client.
  type: str
  returned: when state=present and the client exists
secret:
  description:
    - Client secret. Returned on creation, after regenerate_secret, or when the
      module fetches it for the first time. Empty string for public clients.
  type: str
  returned: when state=present and the client is confidential
  no_log: true
diff:
  description: Before/after diff of changed fields (when run with --diff).
  type: dict
  returned: when in diff mode
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.virtru.dsp_platform.plugins.module_utils.k8s_helper import K8sHelper
from ansible_collections.virtru.dsp_platform.plugins.module_utils.keycloak_helper import KeycloakHelper


# Fields we manage on the client. Order matches kcadm conventions.
MANAGED_BOOL_FIELDS = [
    'enabled',
    'publicClient',
    'standardFlowEnabled',
    'directAccessGrantsEnabled',
    'implicitFlowEnabled',
    'serviceAccountsEnabled',
]
MANAGED_STR_FIELDS = [
    'name', 'description', 'protocol', 'clientAuthenticatorType', 'secret',
]
MANAGED_LIST_FIELDS = ['redirectUris', 'webOrigins']


def _diff_client(existing, desired):
    """Return a dict of fields that differ between existing and desired."""
    diff = {}
    for key, val in desired.items():
        if val is None:
            continue
        cur = existing.get(key)
        if isinstance(val, list):
            # Normalize for comparison (order-independent)
            if sorted(cur or []) != sorted(val):
                diff[key] = val
        elif isinstance(val, dict):
            cur_dict = cur or {}
            merged = dict(cur_dict)
            merged.update(val)
            if merged != cur_dict:
                diff[key] = val
        else:
            if cur != val:
                diff[key] = val
    return diff


def build_desired(p):
    """Build the desired client config dict from module params."""
    desired = {'clientId': p['client_id']}

    for key in MANAGED_BOOL_FIELDS:
        # Map snake_case param to camelCase kcadm field
        param_key = _camel_to_snake(key)
        if param_key in p and p[param_key] is not None:
            desired[key] = p[param_key]

    name = p.get('name')
    if name is not None:
        desired['name'] = name
    if p.get('description') is not None:
        desired['description'] = p['description']
    if p.get('protocol') is not None:
        desired['protocol'] = p['protocol']
    if p.get('client_authenticator_type') is not None:
        desired['clientAuthenticatorType'] = p['client_authenticator_type']
    if p.get('secret') is not None:
        desired['secret'] = p['secret']
    if p.get('redirect_uris') is not None:
        desired['redirectUris'] = p['redirect_uris']
    if p.get('web_origins') is not None:
        desired['webOrigins'] = p['web_origins']
    if p.get('attributes') is not None:
        desired['attributes'] = p['attributes']

    return desired


def _camel_to_snake(camel):
    """Convert camelCase to snake_case."""
    out = []
    for i, ch in enumerate(camel):
        if ch.isupper() and i > 0:
            out.append('_')
        out.append(ch.lower())
    return ''.join(out)


def main():
    module = AnsibleModule(
        argument_spec=dict(
            realm=dict(type='str', required=True),
            state=dict(type='str', choices=['present', 'absent'], default='present'),
            client_id=dict(type='str', required=True),
            name=dict(type='str'),
            description=dict(type='str'),
            enabled=dict(type='bool', default=True),
            public_client=dict(type='bool', default=False),
            client_authenticator_type=dict(type='str', default='client-secret'),
            standard_flow_enabled=dict(type='bool', default=True),
            direct_access_grants_enabled=dict(type='bool', default=True),
            implicit_flow_enabled=dict(type='bool', default=False),
            service_accounts_enabled=dict(type='bool', default=False),
            secret=dict(type='str', no_log=True),
            redirect_uris=dict(type='list', elements='str'),
            web_origins=dict(type='list', elements='str'),
            protocol=dict(type='str', default='openid-connect'),
            attributes=dict(type='dict'),
            service_account_realm_roles=dict(type='list', elements='str'),
            regenerate_secret=dict(type='bool', default=False),
            namespace=dict(type='str', default='virtru'),
            keycloak_statefulset_name=dict(type='str', default='platform-keycloak'),
            admin_user=dict(type='str', default='admin'),
            admin_password=dict(type='str', no_log=True),
            kubectl_bin=dict(type='path', default='kubectl'),
        ),
        supports_check_mode=True,
    )

    p = module.params

    # Inline runner for the helper classes. The K8sHelper expects a `runner`
    # with run_kubectl(); we wrap module.run_command().
    class _Runner:
        def __init__(self, mod, kubectl_bin):
            self.module = mod
            self.kubectl_bin = kubectl_bin

        def run_kubectl(self, args, check_rc=False, parse_json=False):
            cmd = [self.kubectl_bin] + args
            rc, stdout, stderr = self.module.run_command(cmd, check_rc=False)
            if check_rc and rc != 0:
                self.module.fail_json(
                    msg="kubectl failed", cmd=' '.join(cmd),
                    rc=rc, stdout=stdout, stderr=stderr,
                )
            if parse_json and stdout.strip():
                import json as _json
                try:
                    return _json.loads(stdout)
                except (_json.JSONDecodeError, ValueError):
                    return {}
            return rc, stdout, stderr

        def run_command(self, cmd, check_rc=True, parse_json=False, cwd=None):
            rc, stdout, stderr = self.module.run_command(cmd, cwd=cwd, check_rc=False)
            if check_rc and rc != 0:
                self.module.fail_json(
                    msg="Command failed", cmd=' '.join(cmd),
                    rc=rc, stdout=stdout, stderr=stderr,
                )
            return rc, stdout, stderr

    runner = _Runner(module, p['kubectl_bin'])
    k8s = K8sHelper(runner, namespace=p['namespace'])
    kc = KeycloakHelper(k8s, namespace=p['namespace'],
                        statefulset_name=p['keycloak_statefulset_name'])

    # Get admin password
    admin_password = p['admin_password']
    if not admin_password:
        admin_password = kc.get_admin_password()

    # Look up the existing client before any side effects (also validates auth path).
    if not module.check_mode:
        kc.authenticate(admin_password, admin_user=p['admin_user'])
    existing = kc.get_client(p['realm'], p['client_id']) if not module.check_mode else None

    realm = p['realm']
    client_id = p['client_id']
    result = {'changed': False, 'client_id': client_id}

    # ---- absent ----
    if p['state'] == 'absent':
        if existing:
            client_uuid = existing.get('id')
            if not module.check_mode:
                kc.delete_client(realm, client_uuid)
            result['changed'] = True
            result['client_uuid'] = client_uuid
            result['msg'] = "Client '{0}' deleted from realm '{1}'".format(client_id, realm)
        else:
            result['msg'] = "Client '{0}' already absent from realm '{1}'".format(client_id, realm)
        module.exit_json(**result)

    # ---- present ----
    desired = build_desired(p)

    if not existing:
        # Create
        if module.check_mode:
            result['changed'] = True
            result['msg'] = "Would create client '{0}'".format(client_id)
            module.exit_json(**result)

        client_uuid = kc.create_client(realm, desired)
        result['changed'] = True
        result['client_uuid'] = client_uuid

        # Assign service-account realm roles if requested
        sa_roles = p.get('service_account_realm_roles') or []
        if sa_roles and p['service_accounts_enabled']:
            kc.assign_service_account_realm_roles(realm, client_uuid, sa_roles)

        # Fetch the secret (for confidential clients)
        if not p['public_client']:
            secret = kc.get_client_secret(realm, client_uuid)
            if secret:
                result['secret'] = secret
        result['msg'] = "Client '{0}' created in realm '{1}'".format(client_id, realm)
        module.exit_json(**result)

    # Update existing
    client_uuid = existing.get('id')
    result['client_uuid'] = client_uuid

    diff = _diff_client(existing, desired)
    # Secret rotation / explicit secret
    rotate_secret = p['regenerate_secret']
    explicit_secret = p.get('secret')

    if diff:
        if module.check_mode:
            result['changed'] = True
            if module._diff:
                result['diff'] = {
                    'before': {k: existing.get(k) for k in diff},
                    'after': diff,
                }
            module.exit_json(**result)
        kc.update_client(realm, client_uuid, diff)
        result['changed'] = True
        if module._diff:
            result['diff'] = {
                'before': {k: existing.get(k) for k in diff},
                'after': diff,
            }

    # Service-account realm role updates (idempotent inside helper)
    sa_roles = p.get('service_account_realm_roles') or []
    if sa_roles and p['service_accounts_enabled']:
        if module.check_mode:
            result['changed'] = True
        else:
            changed_roles = kc.assign_service_account_realm_roles(
                realm, client_uuid, sa_roles)
            if changed_roles:
                result['changed'] = True

    # Secret handling
    if not p['public_client']:
        if rotate_secret:
            if module.check_mode:
                result['changed'] = True
            else:
                new_secret = kc.regenerate_client_secret(realm, client_uuid)
                result['secret'] = new_secret
                result['changed'] = True
        elif explicit_secret and explicit_secret not in (None, ''):
            # If the user passed an explicit secret, we already included it in
            # `diff` via build_desired; update_client handled it.
            current = kc.get_client_secret(realm, client_uuid)
            result['secret'] = current
        else:
            # Just return the current secret for convenience
            current = kc.get_client_secret(realm, client_uuid)
            if current:
                result['secret'] = current

    result['msg'] = (
        "Client '{0}' updated in realm '{1}'".format(client_id, realm)
        if result['changed']
        else "Client '{0}' already in desired state".format(client_id)
    )
    module.exit_json(**result)


if __name__ == '__main__':
    main()
