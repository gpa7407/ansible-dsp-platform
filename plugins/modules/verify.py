#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Virtru
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Ansible module for post-deploy DSP health verification."""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: verify
short_description: Verify a Virtru DSP deployment is healthy
description:
  - Runs read-only health checks against a freshly-deployed Virtru DSP install.
  - Every check is opt-out via a boolean flag; the module never changes state.
  - Application-layer checks (policy provisioning, KAS round-trips) are out of
    scope - compose this module with C(dsp.tructl.*) tasks in your playbook
    for those.
  - When enabled, the following checks are performed - pod and helm release
    status in the namespace, HTTP probes against C(/healthz) and the
    C(/.wellknown/opentdfconfiguration) endpoint on the platform, gRPC
    reflection list and a C(grpc.health.v1.Health.Check) probe via grpcurl,
    and the Keycloak realm's OIDC well-known configuration endpoint.
version_added: "1.0.0"
options:
  namespace:
    description: Kubernetes namespace where DSP is deployed.
    type: str
    default: virtru
  helm_release:
    description: Helm release name.
    type: str
    default: dsp
  platform_host:
    description:
      - Platform host in C(host:port) form (e.g. C(platform.dsp.vm:443)).
      - Required for HTTP and gRPC checks.
      - If C(platform_url) is supplied this is derived automatically.
    type: str
  platform_url:
    description:
      - Platform HTTPS URL (e.g. C(https://platform.dsp.vm)).
      - Accepted for convenience so the result of C(virtru.dsp_platform.deploy_k3s) can
        be passed directly.
    type: str
  keycloak_url:
    description: Keycloak base URL (e.g. C(https://keycloak.dsp.vm)). Enables the keycloak well-known check.
    type: str
  keycloak_realm:
    description: Keycloak realm to probe.
    type: str
    default: opentdf
  kubectl_bin:
    description: Path to kubectl.
    type: path
    default: kubectl
  helm_bin:
    description: Path to helm.
    type: path
    default: helm
  grpcurl_bin:
    description: Path to grpcurl. Required when C(check_grpc_health) or C(check_grpc_list) is enabled.
    type: path
  tructl_bin:
    description: Path to tructl. Currently unused; accepted for forward-compat.
    type: path
  tls_no_verify:
    description: Skip TLS verification for HTTP and gRPC probes.
    type: bool
    default: true
  check_pods:
    description: Verify pod health.
    type: bool
    default: true
  check_helm:
    description: Verify helm release status.
    type: bool
    default: true
  check_http_healthz:
    description: Probe C(/healthz). Requires C(platform_host) or C(platform_url).
    type: bool
    default: true
  check_wellknown:
    description: Probe C(/.wellknown/opentdfconfiguration). Requires C(platform_host) or C(platform_url).
    type: bool
    default: true
  check_grpc_list:
    description: Probe gRPC reflection via C(grpcurl ... list). Requires C(grpcurl_bin) and C(platform_host).
    type: bool
    default: true
  check_grpc_health:
    description: Probe C(grpc.health.v1.Health.Check). Requires C(grpcurl_bin) and C(platform_host).
    type: bool
    default: true
  check_keycloak:
    description: Probe the Keycloak realm well-known endpoint. Requires C(keycloak_url).
    type: bool
    default: true
  min_running_pods:
    description: Minimum number of pods that must be Running for pod check to pass.
    type: int
    default: 1
  fail_on_error:
    description:
      - If C(true), the module fails when any enabled check fails.
      - If C(false), the module returns the full report and never raises.
    type: bool
    default: true
  timeout:
    description: Total budget (seconds) for retries across all checks.
    type: int
    default: 300
  per_check_timeout:
    description: HTTP/gRPC connect+read timeout (seconds) for each attempt.
    type: int
    default: 10
  retry_interval:
    description: Seconds between retry attempts for a single check.
    type: int
    default: 5
notes:
  - The module is read-only and supports C(check_mode) - it runs the checks normally.
  - For application-layer verification (auth round-trip, policy CRUD) use the
    C(dsp.tructl) collection.
seealso:
  - module: virtru.dsp_platform.deploy_k3s
  - module: virtru.dsp_platform.teardown
author:
  - Greg Paladin (@gpaladin)
'''

EXAMPLES = r'''
- name: Verify DSP after deploy
  virtru.dsp_platform.verify:
    namespace: virtru
    platform_url: "{{ deploy_result.platform_url }}"
    keycloak_url: "{{ deploy_result.keycloak_url }}"
    grpcurl_bin: /opt/virtru/tools-bin/grpcurl
    tls_no_verify: true
  register: verify_result

- name: Run only HTTP probes (skip pod / helm checks - cluster not local)
  virtru.dsp_platform.verify:
    platform_host: platform.dsp.vm:443
    check_pods: false
    check_helm: false
    check_grpc_list: false
    check_grpc_health: false
'''

RETURN = r'''
passed:
  description: True when every enabled check passed.
  type: bool
  returned: always
checks:
  description: Per-check results.
  type: list
  elements: dict
  returned: always
  sample:
    - name: pods_running
      passed: true
      details: "8/8 pods Running in namespace 'virtru'"
      duration_ms: 142
failed_check_names:
  description: Names of checks that failed.
  type: list
  elements: str
  returned: always
summary:
  description: Aggregate counts.
  type: dict
  returned: always
  sample: {total: 7, passed: 7, failed: 0, skipped: 0}
'''

import json
import ssl
import subprocess
import time

from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ansible.module_utils.basic import AnsibleModule


def _ms_since(start):
    return int((time.time() - start) * 1000)


def _http_get(url, timeout, tls_no_verify):
    """HTTP GET. Returns (status_code, body_text, error_or_none)."""
    ctx = None
    if tls_no_verify and url.lower().startswith('https'):
        ctx = ssl._create_unverified_context()

    try:
        req = Request(url, headers={'User-Agent': 'virtru.dsp_platform.verify/1.0'})
        with urlopen(req, timeout=timeout, context=ctx) as resp:
            body = resp.read().decode('utf-8', errors='replace')
            return resp.status, body, None
    except HTTPError as e:
        body = ''
        try:
            body = e.read().decode('utf-8', errors='replace')
        except Exception:
            pass
        return e.code, body, None
    except (URLError, ssl.SSLError, OSError) as e:
        return None, '', str(e)


def _host_port_from_url(url):
    """Parse a URL into 'host:port'. Defaults to 443 for https, 80 for http."""
    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port
    if not port:
        port = 443 if parsed.scheme == 'https' else 80
    return '{0}:{1}'.format(host, port)


def _retry(deadline, interval, fn):
    """Call fn() until it returns (True, details) or deadline is hit.

    fn() must return (passed: bool, details: str).
    """
    last_details = ''
    while True:
        passed, details = fn()
        last_details = details
        if passed:
            return True, details
        if time.time() >= deadline:
            return False, last_details
        time.sleep(interval)


# ---- Individual checks ----

def check_pods(module, deadline, interval, min_running, namespace, kubectl_bin):
    start = time.time()

    def attempt():
        rc, stdout, stderr = module.run_command(
            [kubectl_bin, 'get', 'pods', '-n', namespace, '-o', 'json'],
            check_rc=False,
        )
        if rc != 0:
            return False, "kubectl get pods failed: {0}".format(stderr.strip())
        try:
            data = json.loads(stdout)
        except (json.JSONDecodeError, ValueError) as e:
            return False, "Could not parse kubectl output: {0}".format(e)

        pods = data.get('items', [])
        if not pods:
            return False, "No pods found in namespace '{0}'".format(namespace)

        running = 0
        not_ready = []
        for pod in pods:
            phase = pod.get('status', {}).get('phase', '')
            name = pod.get('metadata', {}).get('name', '?')
            if phase != 'Running':
                not_ready.append('{0}={1}'.format(name, phase))
                continue
            # Check container readiness
            conditions = pod.get('status', {}).get('conditions', [])
            ready_cond = next((c for c in conditions if c.get('type') == 'Ready'), None)
            if ready_cond and ready_cond.get('status') == 'True':
                running += 1
            else:
                not_ready.append('{0}=NotReady'.format(name))

        total = len(pods)
        if running >= min_running and not not_ready:
            return True, "{0}/{1} pods Running and Ready in namespace '{2}'".format(
                running, total, namespace)
        return False, "{0}/{1} pods Ready (issues: {2})".format(
            running, total, ', '.join(not_ready[:5]))

    passed, details = _retry(deadline, interval, attempt)
    return {
        'name': 'pods_running',
        'passed': passed,
        'details': details,
        'duration_ms': _ms_since(start),
    }


def check_helm(module, deadline, interval, namespace, release, helm_bin):
    start = time.time()

    def attempt():
        rc, stdout, stderr = module.run_command(
            [helm_bin, 'status', release, '-n', namespace, '-o', 'json'],
            check_rc=False,
        )
        if rc != 0:
            return False, "helm status failed: {0}".format(stderr.strip())
        try:
            data = json.loads(stdout)
        except (json.JSONDecodeError, ValueError) as e:
            return False, "Could not parse helm output: {0}".format(e)
        status = data.get('info', {}).get('status', '')
        if status == 'deployed':
            return True, "Helm release '{0}' is deployed (revision {1})".format(
                release, data.get('version', '?'))
        return False, "Helm release '{0}' status is '{1}', expected 'deployed'".format(
            release, status)

    passed, details = _retry(deadline, interval, attempt)
    return {
        'name': 'helm_release_deployed',
        'passed': passed,
        'details': details,
        'duration_ms': _ms_since(start),
    }


def check_http_healthz(deadline, interval, per_check_timeout, platform_url, tls_no_verify):
    start = time.time()
    url = platform_url.rstrip('/') + '/healthz'

    def attempt():
        status, body, err = _http_get(url, per_check_timeout, tls_no_verify)
        if err:
            return False, "HTTP error: {0}".format(err)
        if status == 200 and 'SERVING' in body:
            return True, "GET {0} -> 200 SERVING".format(url)
        # 426 (upgrade required) is what the gRPC endpoint returns to plain HTTP
        # before all services are up; treat as transient.
        return False, "GET {0} -> {1} body={2!r}".format(url, status, body[:120])

    passed, details = _retry(deadline, interval, attempt)
    return {
        'name': 'http_healthz',
        'passed': passed,
        'details': details,
        'duration_ms': _ms_since(start),
    }


def check_wellknown(deadline, interval, per_check_timeout, platform_url, tls_no_verify):
    """Probe the OpenTDF well-known configuration endpoint.

    Endpoint path changed across DSP versions:
      - v2.6 and earlier: /.wellknown/opentdfconfiguration
      - v2.7+:            /.well-known/opentdf-configuration
    Probe both and pass if either returns valid JSON.
    """
    start = time.time()
    base = platform_url.rstrip('/')
    candidate_paths = [
        '/.well-known/opentdf-configuration',  # v2.7+
        '/.wellknown/opentdfconfiguration',    # v2.6 and earlier
    ]

    def attempt():
        last_status = None
        last_err = None
        for path in candidate_paths:
            url = base + path
            status, body, err = _http_get(url, per_check_timeout, tls_no_verify)
            if err:
                last_err = err
                continue
            last_status = status
            if status != 200:
                continue
            try:
                data = json.loads(body)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(data, dict) and data:
                return True, "GET {0} -> 200 ({1} keys)".format(url, len(data))
        if last_err:
            return False, "HTTP error: {0}".format(last_err)
        return False, "Neither {0} nor {1} returned 200 JSON (last status {2})".format(
            candidate_paths[0], candidate_paths[1], last_status)

    passed, details = _retry(deadline, interval, attempt)
    return {
        'name': 'wellknown_opentdf_config',
        'passed': passed,
        'details': details,
        'duration_ms': _ms_since(start),
    }


def check_grpc_list(module, deadline, interval, per_check_timeout,
                    platform_host, grpcurl_bin, tls_no_verify):
    start = time.time()
    cmd = [grpcurl_bin, '-connect-timeout', str(per_check_timeout)]
    if tls_no_verify:
        cmd.append('-insecure')
    cmd.extend([platform_host, 'list'])

    def attempt():
        rc, stdout, stderr = module.run_command(cmd, check_rc=False)
        if rc != 0:
            return False, "grpcurl list failed: {0}".format(stderr.strip()[:200])
        services = [s for s in stdout.splitlines() if s.strip()]
        if not services:
            return False, "grpcurl list returned no services"
        return True, "grpcurl list returned {0} services".format(len(services))

    passed, details = _retry(deadline, interval, attempt)
    return {
        'name': 'grpc_reflection_list',
        'passed': passed,
        'details': details,
        'duration_ms': _ms_since(start),
    }


def check_grpc_health(module, deadline, interval, per_check_timeout,
                     platform_host, grpcurl_bin, tls_no_verify):
    start = time.time()
    cmd = [grpcurl_bin, '-connect-timeout', str(per_check_timeout)]
    if tls_no_verify:
        cmd.append('-insecure')
    cmd.extend([platform_host, 'grpc.health.v1.Health.Check'])

    def attempt():
        rc, stdout, stderr = module.run_command(cmd, check_rc=False)
        if rc != 0:
            return False, "grpcurl Health.Check failed: {0}".format(stderr.strip()[:200])
        if 'SERVING' in stdout:
            return True, "grpc.health.v1.Health.Check -> SERVING"
        return False, "grpc.health.v1.Health.Check -> {0!r}".format(stdout.strip())

    passed, details = _retry(deadline, interval, attempt)
    return {
        'name': 'grpc_health_check',
        'passed': passed,
        'details': details,
        'duration_ms': _ms_since(start),
    }


def check_keycloak_realm(deadline, interval, per_check_timeout,
                         keycloak_url, realm, tls_no_verify):
    start = time.time()
    url = '{0}/realms/{1}/.well-known/openid-configuration'.format(
        keycloak_url.rstrip('/'), realm)

    def attempt():
        status, body, err = _http_get(url, per_check_timeout, tls_no_verify)
        if err:
            return False, "HTTP error: {0}".format(err)
        if status != 200:
            return False, "GET {0} -> {1}".format(url, status)
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            return False, "GET {0} -> 200 but body is not JSON".format(url)
        if 'issuer' not in data:
            return False, "OIDC config missing 'issuer'"
        return True, "Keycloak realm '{0}' issuer={1}".format(realm, data['issuer'])

    passed, details = _retry(deadline, interval, attempt)
    return {
        'name': 'keycloak_realm_wellknown',
        'passed': passed,
        'details': details,
        'duration_ms': _ms_since(start),
    }


def main():
    module = AnsibleModule(
        argument_spec=dict(
            namespace=dict(type='str', default='virtru'),
            helm_release=dict(type='str', default='dsp'),
            platform_host=dict(type='str'),
            platform_url=dict(type='str'),
            keycloak_url=dict(type='str'),
            keycloak_realm=dict(type='str', default='opentdf'),
            kubectl_bin=dict(type='path', default='kubectl'),
            helm_bin=dict(type='path', default='helm'),
            grpcurl_bin=dict(type='path'),
            tructl_bin=dict(type='path'),
            tls_no_verify=dict(type='bool', default=True),
            check_pods=dict(type='bool', default=True),
            check_helm=dict(type='bool', default=True),
            check_http_healthz=dict(type='bool', default=True),
            check_wellknown=dict(type='bool', default=True),
            check_grpc_list=dict(type='bool', default=True),
            check_grpc_health=dict(type='bool', default=True),
            check_keycloak=dict(type='bool', default=True),
            min_running_pods=dict(type='int', default=1),
            fail_on_error=dict(type='bool', default=True),
            timeout=dict(type='int', default=300),
            per_check_timeout=dict(type='int', default=10),
            retry_interval=dict(type='int', default=5),
        ),
        supports_check_mode=True,
    )

    p = module.params

    # Derive platform_host from platform_url if needed
    platform_url = p.get('platform_url')
    platform_host = p.get('platform_host')
    if platform_url and not platform_host:
        platform_host = _host_port_from_url(platform_url)
    if platform_host and not platform_url:
        platform_url = 'https://{0}'.format(platform_host.split(':')[0])

    deadline = time.time() + p['timeout']
    interval = p['retry_interval']
    per_check_timeout = p['per_check_timeout']

    checks = []
    skipped = []

    if p['check_pods']:
        checks.append(check_pods(
            module, deadline, interval, p['min_running_pods'],
            p['namespace'], p['kubectl_bin'],
        ))
    else:
        skipped.append('pods_running')

    if p['check_helm']:
        checks.append(check_helm(
            module, deadline, interval,
            p['namespace'], p['helm_release'], p['helm_bin'],
        ))
    else:
        skipped.append('helm_release_deployed')

    if p['check_http_healthz']:
        if platform_url:
            checks.append(check_http_healthz(
                deadline, interval, per_check_timeout,
                platform_url, p['tls_no_verify'],
            ))
        else:
            skipped.append('http_healthz (no platform_url)')
    else:
        skipped.append('http_healthz (disabled)')

    if p['check_wellknown']:
        if platform_url:
            checks.append(check_wellknown(
                deadline, interval, per_check_timeout,
                platform_url, p['tls_no_verify'],
            ))
        else:
            skipped.append('wellknown_opentdf_config (no platform_url)')
    else:
        skipped.append('wellknown_opentdf_config (disabled)')

    if p['check_grpc_list']:
        if p['grpcurl_bin'] and platform_host:
            checks.append(check_grpc_list(
                module, deadline, interval, per_check_timeout,
                platform_host, p['grpcurl_bin'], p['tls_no_verify'],
            ))
        else:
            skipped.append('grpc_reflection_list (need grpcurl_bin and platform_host)')
    else:
        skipped.append('grpc_reflection_list (disabled)')

    if p['check_grpc_health']:
        if p['grpcurl_bin'] and platform_host:
            checks.append(check_grpc_health(
                module, deadline, interval, per_check_timeout,
                platform_host, p['grpcurl_bin'], p['tls_no_verify'],
            ))
        else:
            skipped.append('grpc_health_check (need grpcurl_bin and platform_host)')
    else:
        skipped.append('grpc_health_check (disabled)')

    if p['check_keycloak']:
        if p['keycloak_url']:
            checks.append(check_keycloak_realm(
                deadline, interval, per_check_timeout,
                p['keycloak_url'], p['keycloak_realm'], p['tls_no_verify'],
            ))
        else:
            skipped.append('keycloak_realm_wellknown (no keycloak_url)')
    else:
        skipped.append('keycloak_realm_wellknown (disabled)')

    passed = all(c['passed'] for c in checks)
    failed_names = [c['name'] for c in checks if not c['passed']]

    summary = {
        'total': len(checks),
        'passed': sum(1 for c in checks if c['passed']),
        'failed': len(failed_names),
        'skipped': len(skipped),
    }

    result = {
        'changed': False,
        'passed': passed,
        'checks': checks,
        'failed_check_names': failed_names,
        'skipped': skipped,
        'summary': summary,
    }

    if not passed and p['fail_on_error']:
        module.fail_json(msg="DSP verification failed", **result)

    module.exit_json(**result)


if __name__ == '__main__':
    main()
