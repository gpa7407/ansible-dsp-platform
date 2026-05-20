#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Virtru
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Programmatic values.yaml builder for DSP Helm deployments.

Replaces the 40+ yq eval mutations in provision-values.sh with a
declarative Python builder that produces a complete values dict.
"""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import copy

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


def _version_ge(version_a, version_b):
    """Compare two semver-ish version strings."""
    def parse(v):
        return [int(x) for x in v.lstrip('v').split('.')]
    try:
        a_parts = parse(version_a)
        b_parts = parse(version_b)
    except (ValueError, AttributeError):
        return False
    max_len = max(len(a_parts), len(b_parts))
    a_parts.extend([0] * (max_len - len(a_parts)))
    b_parts.extend([0] * (max_len - len(b_parts)))
    return a_parts >= b_parts


class ValuesBuilder:
    """Build a complete DSP Helm values.yaml as a Python dict.

    Args:
        dsp_tag: DSP version tag (e.g., 'v2.0.6.1').
        domain: Base domain (e.g., 'dsp.vm').
        registry_fqdn: Container registry FQDN (e.g., 'localhost:8888').
        namespace: Kubernetes namespace.
        platform_hostname: Override platform hostname (default: platform.{domain}).
        keycloak_hostname: Override Keycloak hostname (default: keycloak.{domain}).
        tagging_hostname: Override tagging hostname (default: tagging-pdp.{domain}).
        playground: Use embedded Keycloak/PostgreSQL (default: True).
        db_host: Database hostname (default: 'postgresql').
        keycloak_admin_password: Keycloak admin password.
        keycloak_realm: Keycloak realm name (default: 'opentdf').
        host_aliases: List of {'ip': ..., 'hostnames': [...]} dicts.
        additional_trusted_certs: List of cert source dicts for TLS.
        cors_enabled: Enable CORS (default: True).
        cors_origins: List of allowed origins.
        deployment_mode: DSP mode (all, core, kas).
        mac_m4_host: Enable Mac M4 workaround (default: False).
        extra_values: Dict of additional values to merge.
    """

    def __init__(self, dsp_tag, domain, registry_fqdn,
                 namespace='virtru',
                 platform_hostname=None,
                 keycloak_hostname=None,
                 tagging_hostname=None,
                 playground=True,
                 db_host='postgresql',
                 keycloak_admin_password='',
                 keycloak_realm='opentdf',
                 host_aliases=None,
                 additional_trusted_certs=None,
                 cors_enabled=True,
                 cors_origins=None,
                 deployment_mode='all',
                 mac_m4_host=False,
                 extra_values=None):
        self.dsp_tag = dsp_tag
        self.domain = domain
        self.registry_fqdn = registry_fqdn
        self.namespace = namespace
        self.platform_hostname = platform_hostname or 'platform.{0}'.format(domain)
        self.keycloak_hostname = keycloak_hostname or 'keycloak.{0}'.format(domain)
        self.tagging_hostname = tagging_hostname or 'tagging-pdp.{0}'.format(domain)
        self.playground = playground
        self.db_host = db_host
        self.keycloak_admin_password = keycloak_admin_password
        self.keycloak_realm = keycloak_realm
        self.host_aliases = host_aliases or []
        self.additional_trusted_certs = additional_trusted_certs
        self.cors_enabled = cors_enabled
        self.cors_origins = cors_origins or ['*', 'localhost:3000']
        self.deployment_mode = deployment_mode
        self.mac_m4_host = mac_m4_host
        self.extra_values = extra_values or {}

        # Derived URLs
        self.auth_url = 'https://{0}'.format(self.keycloak_hostname)
        self.platform_url = 'https://{0}'.format(self.platform_hostname)

    def build(self):
        """Build and return the complete values dict."""
        values = {}

        # Top-level anchor values (these are referenced via YAML aliases in the chart)
        values['platformRegistry'] = '{0}/virtru/data-security-platform'.format(self.registry_fqdn)
        values['platformHostname'] = self.platform_hostname
        values['platformEndpoint'] = self.platform_url
        values['authEndpoint'] = self.auth_url
        values['issuer'] = '{0}/realms/{1}'.format(self.auth_url, self.keycloak_realm)
        values['tokenEndpoint'] = '{0}/realms/{1}/protocol/openid-connect/token'.format(
            self.auth_url, self.keycloak_realm
        )
        values['dbHost'] = self.db_host
        values['dbPort'] = 5432
        values['databaseName'] = 'opentdf'
        values['dbUser'] = 'opentdf'
        values['tikaRepository'] = '{0}/virtru/tika'.format(self.registry_fqdn)

        # v2.6+ image anchors
        if _version_ge(self.dsp_tag, 'v2.6'):
            values['keycloakImage'] = {
                'registry': self.registry_fqdn,
                'repository': 'virtru/keycloak',
            }
            values['keycloakConfigCliImage'] = {
                'registry': self.registry_fqdn,
                'repository': 'virtru/keycloak-config-cli',
            }
            values['postgresImage'] = {
                'registry': self.registry_fqdn,
                'repository': 'virtru/postgresql',
            }
            values['osShellImage'] = {
                'registry': self.registry_fqdn,
                'repository': 'virtru/os-shell',
            }

        # Platform section
        platform = {}
        platform['playground'] = self.playground
        platform['image'] = {'tag': self.dsp_tag}
        platform['ingress'] = {'enabled': True}

        # Keycloak subsection
        kc = {}
        kc['ingress'] = {'enabled': False}
        kc['auth'] = {'adminPassword': self.keycloak_admin_password}

        kc_extra_env = [{'name': 'KC_HEALTH_ENABLED', 'value': 'true'}]
        if self.mac_m4_host:
            kc_extra_env.append({'name': 'JAVA_TOOL_OPTIONS', 'value': '-XX:UseSVE=0'})
        kc['extraEnvVars'] = kc_extra_env

        # Disable keycloakConfigCli - we provision via tructl keycloak-from-config instead
        kc_config_cli = {'enabled': False}
        if self.mac_m4_host:
            kc_config_cli['extraEnvVars'] = [
                {'name': 'JAVA_TOOL_OPTIONS', 'value': '-XX:UseSVE=0'}
            ]
        kc['keycloakConfigCli'] = kc_config_cli

        platform['keycloak'] = kc

        # TLS trusted certs
        if self.additional_trusted_certs:
            platform.setdefault('server', {}).setdefault('tls', {})
            platform['server']['tls']['additionalTrustedCerts'] = self.additional_trusted_certs
        else:
            # Default: trust the gateway TLS cert
            platform.setdefault('server', {}).setdefault('tls', {})
            platform['server']['tls']['additionalTrustedCerts'] = [
                {
                    'secret': {
                        'name': 'dsp-gateway-tls',
                        'items': [{'key': 'tls.crt', 'path': 'platform.crt'}],
                    }
                },
            ]

        # Host aliases
        if self.host_aliases:
            platform['hostAliases'] = self.host_aliases

        # CORS
        if self.cors_enabled:
            platform.setdefault('server', {})['cors'] = {
                'enabled': True,
                'allowedorigins': self.cors_origins,
            }

        # Database
        platform['db'] = {'host': self.db_host}
        if _version_ge(self.dsp_tag, 'v2.6'):
            platform['db']['password'] = {
                'secret': {
                    'name': 'opentdf-db-credentials',
                    'key': 'password',
                },
            }

        # Services
        services = {
            'dsp_services': {
                'tdfviewer': {'enabled': False},
                'outlook': {'enabled': self.deployment_mode in ('outlook', 'all') and False},
                'sharepoint': {'enabled': self.deployment_mode in ('sharepoint', 'all') and False},
            },
            'policyimportexport': {
                'enabled': True,
                'privatesignkey': 'dsp-keys/policyimportexport/cosign.key',
                'privatesignkeypassphrasepath': 'dsp-keys/policyimportexport/cosign.pass',
                'truststore': 'dsp-keys/policyimportexport',
            },
        }
        platform['services'] = services

        # v2.6+ specific settings
        if _version_ge(self.dsp_tag, 'v2.6'):
            platform['enable_pprof'] = True
            platform['http'] = {
                'readTimeout': '30s',
                'writeTimeout': '30s',
            }
            platform['services']['dsp_services']['taggingPDP'] = {
                'tikaServerUrl': 'http://tikaservice.{0}.svc.cluster.local:9998'.format(
                    self.namespace
                ),
            }

        values['platform'] = platform

        # Tagging PDP host aliases (mirror platform)
        if self.host_aliases:
            values['taggingPDP'] = {'hostAliases': self.host_aliases}

        # Merge extra values (deep merge)
        if self.extra_values:
            values = self._deep_merge(values, self.extra_values)

        return values

    def build_keycloak_data(self, clients=None, users=None):
        """Build keycloak_data.yaml content for provisioning.

        Args:
            clients: List of client dicts (optional, uses defaults).
            users: List of user dicts (optional, uses defaults).

        Returns:
            Dict suitable for YAML serialization.
        """
        data = {
            'baseUrl': self.auth_url,
            'serverBaseUrl': self.platform_url,
            'redirectUris': [
                '{0}/*'.format(self.platform_url),
                '{0}/*'.format(self.auth_url),
            ],
        }

        realms = [{
            'name': self.keycloak_realm,
        }]

        # Add v2.6+ realm roles
        if _version_ge(self.dsp_tag, 'v2.6'):
            realms[0]['custom_realm_roles'] = [
                {'name': 'dsp-org-admin'},
                {'name': 'dsp-admin'},
                {'name': 'dsp-standard'},
            ]

        if clients:
            realms[0]['clients'] = clients
        if users:
            realms[0]['users'] = users

        data['realms'] = realms
        return data

    def to_yaml(self):
        """Serialize built values to YAML string."""
        if not HAS_YAML:
            raise ImportError("PyYAML is required for to_yaml()")
        return yaml.dump(self.build(), default_flow_style=False, sort_keys=False)

    def write(self, path):
        """Write built values to a YAML file."""
        if not HAS_YAML:
            raise ImportError("PyYAML is required for write()")
        values = self.build()
        with open(path, 'w') as f:
            yaml.dump(values, f, default_flow_style=False, sort_keys=False)

    def write_keycloak_data(self, path, clients=None, users=None):
        """Write keycloak_data.yaml to a file."""
        if not HAS_YAML:
            raise ImportError("PyYAML is required for write_keycloak_data()")
        data = self.build_keycloak_data(clients=clients, users=users)
        with open(path, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    @staticmethod
    def _deep_merge(base, override):
        """Deep merge two dicts. Override takes precedence."""
        result = copy.deepcopy(base)
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = ValuesBuilder._deep_merge(result[key], value)
            else:
                result[key] = copy.deepcopy(value)
        return result
