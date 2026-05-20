#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Virtru
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Keycloak helper utilities for virtru.dsp_platform modules.

Provides Keycloak administration via kcadm.sh executed inside the Keycloak
pod using kubectl exec. This is the fallback approach for air-gapped
environments where community.general.keycloak modules may not be available.
"""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import json


class KeycloakHelper:
    """Helper for Keycloak operations via kcadm.sh inside the KC pod."""

    KCADM_PATH = '/opt/bitnami/keycloak/bin/kcadm.sh'
    LOCAL_SERVER = 'http://localhost:8080'
    # kcadm.sh defaults its config file to ~/.keycloak/kcadm.config which is
    # not writable in the keycloak container. Override to a writable path.
    KCADM_CONFIG = '/tmp/kcadm.config'

    def __init__(self, k8s_helper, namespace='virtru',
                 statefulset_name='platform-keycloak'):
        self.k8s = k8s_helper
        self.namespace = namespace
        self.statefulset_name = statefulset_name
        self._pod_name = None
        self._authenticated = False

    @property
    def pod_name(self):
        """Find the Keycloak pod name."""
        if self._pod_name:
            return self._pod_name

        # Try statefulset pod naming convention first
        candidate = '{0}-0'.format(self.statefulset_name)
        rc, _, _ = self.k8s.runner.run_kubectl(
            ['get', 'pod', candidate, '-n', self.namespace],
            check_rc=False,
        )
        if rc == 0:
            self._pod_name = candidate
            return self._pod_name

        # Fallback: search by label
        rc, stdout, _ = self.k8s.runner.run_kubectl([
            'get', 'pods', '-n', self.namespace,
            '-l', 'app.kubernetes.io/name=keycloak',
            '-o', 'jsonpath={.items[0].metadata.name}',
        ], check_rc=False)

        if rc == 0 and stdout.strip():
            self._pod_name = stdout.strip()
            return self._pod_name

        self.k8s.runner.module.fail_json(
            msg="Could not find Keycloak pod in namespace {0}".format(self.namespace)
        )

    def _kcadm(self, args, check_rc=True):
        """Run kcadm.sh inside the Keycloak pod.

        kcadm.sh expects `--config <FILE>` after the command/subcommand and
        before any flags (e.g. `get clients --config /tmp/kcadm.config -r realm`).
        We inject it before the first arg that starts with '-'. The default
        config path ~/.keycloak/kcadm.config is not writable in the bitnami
        image so this override is mandatory.
        """
        new_args = list(args)
        inject_at = len(new_args)
        for i, a in enumerate(new_args):
            if a.startswith('-'):
                inject_at = i
                break
        new_args[inject_at:inject_at] = ['--config', self.KCADM_CONFIG]
        cmd = [self.KCADM_PATH] + new_args
        return self.k8s.kubectl_exec(self.pod_name, cmd)

    def authenticate(self, admin_password, admin_user='admin'):
        """Authenticate kcadm.sh to Keycloak's local admin endpoint."""
        rc, stdout, stderr = self._kcadm([
            'config', 'credentials',
            '--server', self.LOCAL_SERVER,
            '--realm', 'master',
            '--user', admin_user,
            '--password', admin_password,
        ])

        if rc != 0:
            self.k8s.runner.module.fail_json(
                msg="Failed to authenticate to Keycloak",
                stdout=stdout,
                stderr=stderr,
            )
        self._authenticated = True

    def _ensure_auth(self):
        """Ensure we've authenticated."""
        if not self._authenticated:
            self.k8s.runner.module.fail_json(
                msg="KeycloakHelper: must call authenticate() before other operations"
            )

    # ---- Client operations ----

    def get_client(self, realm, client_id):
        """Return the client dict for client_id, or None if not found."""
        self._ensure_auth()
        rc, stdout, _ = self._kcadm([
            'get', 'clients',
            '-r', realm,
            '-q', 'clientId={0}'.format(client_id),
        ], check_rc=False)

        if rc != 0 or not stdout.strip():
            return None

        try:
            clients = json.loads(stdout)
            if isinstance(clients, list):
                for client in clients:
                    if client.get('clientId') == client_id:
                        return client
        except (json.JSONDecodeError, ValueError):
            pass
        return None

    def get_client_uuid(self, realm, client_id):
        """Return the internal UUID for a client, or None if not found."""
        client = self.get_client(realm, client_id)
        if client:
            return client.get('id')
        return None

    @staticmethod
    def _kcadm_set_args(client_config):
        """Convert a client config dict into kcadm `-s key=value` args."""
        args = []
        for key, value in client_config.items():
            if value is None:
                continue
            if isinstance(value, bool):
                args.extend(['-s', '{0}={1}'.format(key, str(value).lower())])
            elif isinstance(value, (list, dict)):
                args.extend(['-s', '{0}={1}'.format(key, json.dumps(value))])
            else:
                args.extend(['-s', '{0}={1}'.format(key, value)])
        return args

    def create_client(self, realm, client_config):
        """Create a Keycloak client. Returns the new client UUID."""
        self._ensure_auth()
        client_id = client_config['clientId']

        existing = self.get_client(realm, client_id)
        if existing:
            return existing.get('id')

        cmd = ['create', 'clients', '-r', realm] + self._kcadm_set_args(client_config)
        rc, stdout, stderr = self._kcadm(cmd, check_rc=False)
        if rc != 0:
            self.k8s.runner.module.fail_json(
                msg="Failed to create Keycloak client '{0}'".format(client_id),
                stdout=stdout,
                stderr=stderr,
            )

        # kcadm prints "Created new client with id '<uuid>'" to stderr
        return self.get_client_uuid(realm, client_id)

    def update_client(self, realm, client_uuid, updates):
        """Apply partial updates to a client. Returns True if any change applied."""
        self._ensure_auth()
        if not updates:
            return False

        cmd = (['update', 'clients/{0}'.format(client_uuid), '-r', realm]
               + self._kcadm_set_args(updates))
        rc, stdout, stderr = self._kcadm(cmd, check_rc=False)
        if rc != 0:
            self.k8s.runner.module.fail_json(
                msg="Failed to update Keycloak client {0}".format(client_uuid),
                stdout=stdout,
                stderr=stderr,
            )
        return True

    def delete_client(self, realm, client_uuid):
        """Delete a client by UUID. Returns True if deleted."""
        self._ensure_auth()
        rc, stdout, stderr = self._kcadm([
            'delete', 'clients/{0}'.format(client_uuid),
            '-r', realm,
        ], check_rc=False)
        if rc != 0:
            self.k8s.runner.module.fail_json(
                msg="Failed to delete Keycloak client {0}".format(client_uuid),
                stdout=stdout,
                stderr=stderr,
            )
        return True

    def get_client_secret(self, realm, client_uuid):
        """Return the current secret for a confidential client."""
        self._ensure_auth()
        rc, stdout, _ = self._kcadm([
            'get', 'clients/{0}/client-secret'.format(client_uuid),
            '-r', realm,
        ], check_rc=False)
        if rc != 0 or not stdout.strip():
            return None
        try:
            data = json.loads(stdout)
            return data.get('value')
        except (json.JSONDecodeError, ValueError):
            return None

    def regenerate_client_secret(self, realm, client_uuid):
        """Force-rotate a client's secret and return the new value."""
        self._ensure_auth()
        rc, stdout, stderr = self._kcadm([
            'create', 'clients/{0}/client-secret'.format(client_uuid),
            '-r', realm,
        ], check_rc=False)
        if rc != 0:
            self.k8s.runner.module.fail_json(
                msg="Failed to regenerate secret for client {0}".format(client_uuid),
                stdout=stdout,
                stderr=stderr,
            )
        return self.get_client_secret(realm, client_uuid)

    # ---- Realm role operations ----

    def get_realm_role(self, realm, role_name):
        """Return the realm role dict, or None if missing."""
        self._ensure_auth()
        rc, stdout, _ = self._kcadm([
            'get', 'roles/{0}'.format(role_name),
            '-r', realm,
        ], check_rc=False)
        if rc != 0 or not stdout.strip():
            return None
        try:
            return json.loads(stdout)
        except (json.JSONDecodeError, ValueError):
            return None

    def create_realm_role(self, realm, role_name):
        """Create a realm role if it doesn't exist."""
        self._ensure_auth()
        if self.get_realm_role(realm, role_name):
            return False

        rc, stdout, stderr = self._kcadm([
            'create', 'roles', '-r', realm,
            '-s', 'name={0}'.format(role_name),
        ], check_rc=False)
        if rc != 0:
            self.k8s.runner.module.fail_json(
                msg="Failed to create realm role '{0}'".format(role_name),
                stdout=stdout,
                stderr=stderr,
            )
        return True

    # ---- Service-account role operations ----

    def get_service_account_user_id(self, realm, client_uuid):
        """Return the user-id of the service account user for a client."""
        self._ensure_auth()
        rc, stdout, _ = self._kcadm([
            'get', 'clients/{0}/service-account-user'.format(client_uuid),
            '-r', realm,
        ], check_rc=False)
        if rc != 0 or not stdout.strip():
            return None
        try:
            return json.loads(stdout).get('id')
        except (json.JSONDecodeError, ValueError):
            return None

    def list_service_account_realm_roles(self, realm, client_uuid):
        """Return assigned realm role names for a client's service account."""
        sa_user_id = self.get_service_account_user_id(realm, client_uuid)
        if not sa_user_id:
            return []
        rc, stdout, _ = self._kcadm([
            'get', 'users/{0}/role-mappings/realm'.format(sa_user_id),
            '-r', realm,
        ], check_rc=False)
        if rc != 0 or not stdout.strip():
            return []
        try:
            roles = json.loads(stdout)
            return [r.get('name') for r in roles if r.get('name')]
        except (json.JSONDecodeError, ValueError):
            return []

    def assign_service_account_realm_roles(self, realm, client_uuid, role_names):
        """Assign realm roles to a client's service account. Idempotent."""
        self._ensure_auth()
        if not role_names:
            return False

        existing = set(self.list_service_account_realm_roles(realm, client_uuid))
        to_add = [r for r in role_names if r not in existing]
        if not to_add:
            return False

        sa_user_id = self.get_service_account_user_id(realm, client_uuid)
        if not sa_user_id:
            self.k8s.runner.module.fail_json(
                msg="Service account user not found for client {0} "
                    "(serviceAccountsEnabled must be true)".format(client_uuid)
            )

        # kcadm.sh add-roles is the documented path.
        cmd = ['add-roles', '-r', realm,
               '--uusername', 'service-account-' + self._client_id_for_uuid(realm, client_uuid)]
        for role_name in to_add:
            cmd.extend(['--rolename', role_name])

        rc, stdout, stderr = self._kcadm(cmd, check_rc=False)
        if rc != 0:
            self.k8s.runner.module.fail_json(
                msg="Failed to assign realm roles to service account",
                roles=to_add,
                stdout=stdout,
                stderr=stderr,
            )
        return True

    def _client_id_for_uuid(self, realm, client_uuid):
        """Helper: look up the human clientId given a client UUID."""
        rc, stdout, _ = self._kcadm([
            'get', 'clients/{0}'.format(client_uuid),
            '-r', realm,
        ], check_rc=False)
        if rc != 0 or not stdout.strip():
            return ''
        try:
            return json.loads(stdout).get('clientId', '')
        except (json.JSONDecodeError, ValueError):
            return ''

    # ---- Misc ----

    def get_admin_password(self):
        """Retrieve Keycloak admin password from K8s secret."""
        password = self.k8s.get_secret_value(self.statefulset_name, 'admin-password')
        if not password:
            self.k8s.runner.module.fail_json(
                msg="Could not retrieve Keycloak admin password from secret '{0}'".format(
                    self.statefulset_name
                )
            )
        return password
