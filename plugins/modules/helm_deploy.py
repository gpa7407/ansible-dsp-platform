#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Virtru
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Ansible module: full-featured helm upgrade/install/uninstall wrapper."""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: helm_deploy
short_description: Install, upgrade, or uninstall a Helm release
description:
  - Thin but full-featured wrapper around C(helm upgrade --install) and
    C(helm uninstall).
  - Idempotent - reports C(changed=true) only when the release was created,
    its revision incremented, or it was removed.
  - Supports inline values (dict) merged with values files, plus C(--set),
    C(--set-string), and C(--set-file).
  - Used by C(virtru.dsp_platform.deploy_k3s) internally and exposed as a standalone
    module for arbitrary chart installs.
version_added: "1.0.0"
options:
  namespace:
    description: Kubernetes namespace for the release.
    type: str
    required: true
  release_name:
    description: Helm release name.
    type: str
    required: true
  state:
    description:
      - C(present) ensures the release is installed/upgraded.
      - C(absent) uninstalls the release if it exists.
    type: str
    choices: [present, absent]
    default: present
  chart:
    description:
      - Chart reference. Path to a .tgz, a directory, an OCI ref (C(oci://...)),
        or C(repo/chart) when C(repo) is set.
      - Required for C(state=present).
    type: str
  repo:
    description: Chart repository URL (when C(chart) is just a chart name).
    type: str
  version:
    description: Chart version pin.
    type: str
  values_files:
    description: List of values file paths (in order, later overrides earlier).
    type: list
    elements: path
  values:
    description: Inline values dict (merged after C(values_files)).
    type: dict
  set_values:
    description: Dict of values to pass via C(--set k=v).
    type: dict
  set_string_values:
    description: Dict of values to pass via C(--set-string k=v).
    type: dict
  set_file_values:
    description: Dict of values to pass via C(--set-file k=file_path).
    type: dict
  wait:
    description: Wait for resources to be ready before returning.
    type: bool
    default: true
  timeout:
    description: Helm timeout (e.g. C(15m)).
    type: str
    default: 15m
  atomic:
    description: Roll back on failure.
    type: bool
    default: false
  cleanup_on_fail:
    description: Clean up newly-created resources on failure.
    type: bool
    default: false
  force:
    description: Force resource updates by replacement.
    type: bool
    default: false
  recreate_pods:
    description: Recreate pods belonging to the release.
    type: bool
    default: false
  create_namespace:
    description: Create the namespace if it doesn't exist.
    type: bool
    default: false
  dependency_update:
    description: Run C(helm dependency update) before install.
    type: bool
    default: false
  reset_values:
    description: Reset values to chart defaults (only relevant on upgrade).
    type: bool
    default: false
  disable_hooks:
    description: Skip running release hooks.
    type: bool
    default: false
  description:
    description: Human-readable release description.
    type: str
  helm_bin:
    description: Path to helm.
    type: path
    default: helm
  kubectl_bin:
    description: Path to kubectl.
    type: path
    default: kubectl
  kubeconfig:
    description: Path to kubeconfig (overrides C($KUBECONFIG)).
    type: path
  debug:
    description: Pass C(--debug) to helm.
    type: bool
    default: false
notes:
  - When inline C(values) is provided, the module writes a temp YAML file and
    appends it as an extra C(--values) argument. PyYAML is required for this.
seealso:
  - module: virtru.dsp_platform.deploy_k3s
  - module: virtru.dsp_platform.teardown
author:
  - Greg Paladin (@gpaladin)
'''

EXAMPLES = r'''
- name: Install DSP chart from local tgz
  virtru.dsp_platform.helm_deploy:
    namespace: virtru
    release_name: dsp
    chart: /opt/virtru/charts/data-security-platform-2.0.6.1.tgz
    values_files:
      - /opt/virtru/values.yaml
      - /opt/virtru/tagging-pdp-workflows.yaml
    wait: true
    timeout: 20m
    atomic: true

- name: Install nginx from a remote repo, pin version, atomic
  virtru.dsp_platform.helm_deploy:
    namespace: web
    release_name: nginx
    chart: nginx
    repo: https://charts.bitnami.com/bitnami
    version: 15.4.4
    create_namespace: true
    values:
      service:
        type: ClusterIP
    set_string_values:
      image.tag: "1.25.3-debian-12-r0"
    atomic: true

- name: Uninstall a release
  virtru.dsp_platform.helm_deploy:
    namespace: virtru
    release_name: dsp
    state: absent
    wait: true
'''

RETURN = r'''
changed:
  description: Whether the release was created/upgraded/removed.
  type: bool
  returned: always
release_name:
  description: Release name.
  type: str
  returned: always
namespace:
  description: Namespace.
  type: str
  returned: always
chart:
  description: Chart reference passed to helm.
  type: str
  returned: when state=present
version:
  description: Resolved chart version (helm-reported).
  type: str
  returned: when state=present and release exists post-run
revision:
  description: Resolved release revision.
  type: int
  returned: when state=present and release exists post-run
status:
  description: Helm-reported release status (e.g. deployed, failed, uninstalled).
  type: str
  returned: always
notes:
  description: Contents of the chart's NOTES.txt (from C(helm status)).
  type: str
  returned: when state=present and release exists post-run
stdout:
  description: Combined stdout from the helm command.
  type: str
  returned: when changed
'''

import os
import tempfile

from ansible.module_utils.basic import AnsibleModule


def _build_helm_runner(module, helm_bin):
    """Return a callable that runs helm with module.run_command."""
    def run_helm(args, check_rc=True):
        cmd = [helm_bin] + args
        rc, stdout, stderr = module.run_command(cmd, check_rc=False)
        if check_rc and rc != 0:
            module.fail_json(
                msg="helm command failed",
                cmd=' '.join(cmd),
                rc=rc,
                stdout=stdout,
                stderr=stderr,
            )
        return rc, stdout, stderr
    return run_helm


def _get_release_status(run_helm, namespace, release, kubeconfig=None):
    """Return a dict with revision/status/notes/chart_version, or None if missing."""
    import json as _json
    args = []
    if kubeconfig:
        args.extend(['--kubeconfig', kubeconfig])
    args.extend(['status', release, '-n', namespace, '-o', 'json'])
    rc, stdout, _ = run_helm(args, check_rc=False)
    if rc != 0:
        return None
    try:
        data = _json.loads(stdout)
    except (_json.JSONDecodeError, ValueError):
        return None
    info = data.get('info', {})
    chart = data.get('chart', {}) or {}
    chart_meta = chart.get('metadata', {}) if isinstance(chart, dict) else {}
    return {
        'revision': data.get('version', info.get('revision', 0)),
        'status': info.get('status', ''),
        'notes': info.get('notes', ''),
        'chart_version': chart_meta.get('version', ''),
        'chart_name': chart_meta.get('name', ''),
    }


def _write_inline_values(values):
    """Write an inline values dict to a temp YAML file. Returns the path."""
    try:
        import yaml
    except ImportError:
        return None, "PyYAML is required to use the 'values' parameter"
    tmpf = tempfile.NamedTemporaryFile(
        mode='w', suffix='.yaml', delete=False, prefix='helm_deploy_values_')
    try:
        yaml.dump(values, tmpf, default_flow_style=False, sort_keys=False)
    finally:
        tmpf.close()
    return tmpf.name, None


def main():
    module = AnsibleModule(
        argument_spec=dict(
            namespace=dict(type='str', required=True),
            release_name=dict(type='str', required=True),
            state=dict(type='str', choices=['present', 'absent'], default='present'),
            chart=dict(type='str'),
            repo=dict(type='str'),
            version=dict(type='str'),
            values_files=dict(type='list', elements='path'),
            values=dict(type='dict'),
            set_values=dict(type='dict'),
            set_string_values=dict(type='dict'),
            set_file_values=dict(type='dict'),
            wait=dict(type='bool', default=True),
            timeout=dict(type='str', default='15m'),
            atomic=dict(type='bool', default=False),
            cleanup_on_fail=dict(type='bool', default=False),
            force=dict(type='bool', default=False),
            recreate_pods=dict(type='bool', default=False),
            create_namespace=dict(type='bool', default=False),
            dependency_update=dict(type='bool', default=False),
            reset_values=dict(type='bool', default=False),
            disable_hooks=dict(type='bool', default=False),
            description=dict(type='str'),
            helm_bin=dict(type='path', default='helm'),
            kubectl_bin=dict(type='path', default='kubectl'),
            kubeconfig=dict(type='path'),
            debug=dict(type='bool', default=False),
        ),
        required_if=[
            ('state', 'present', ['chart']),
        ],
        supports_check_mode=True,
    )

    p = module.params
    run_helm = _build_helm_runner(module, p['helm_bin'])

    namespace = p['namespace']
    release = p['release_name']
    kubeconfig = p['kubeconfig']

    before = _get_release_status(run_helm, namespace, release, kubeconfig=kubeconfig)
    before_revision = int(before.get('revision', 0)) if before else 0

    # ---- absent ----
    if p['state'] == 'absent':
        if not before:
            module.exit_json(
                changed=False,
                release_name=release,
                namespace=namespace,
                status='uninstalled',
                msg="Release '{0}' is already absent".format(release),
            )

        if module.check_mode:
            module.exit_json(
                changed=True,
                release_name=release,
                namespace=namespace,
                status='would-uninstall',
                msg="Would uninstall release '{0}'".format(release),
            )

        args = []
        if kubeconfig:
            args.extend(['--kubeconfig', kubeconfig])
        args.extend(['uninstall', release, '-n', namespace])
        if p['wait']:
            args.extend(['--wait', '--timeout', p['timeout']])
        if p['disable_hooks']:
            args.append('--no-hooks')

        rc, stdout, stderr = run_helm(args)
        module.exit_json(
            changed=True,
            release_name=release,
            namespace=namespace,
            status='uninstalled',
            stdout=stdout,
        )

    # ---- present ----
    if module.check_mode:
        # We can't determine without actually running helm whether values
        # would produce a new revision, but we know whether the release exists.
        module.exit_json(
            changed=True,
            release_name=release,
            namespace=namespace,
            status='would-{0}'.format('upgrade' if before else 'install'),
            chart=p['chart'],
            msg="Would {0} release '{1}'".format(
                'upgrade' if before else 'install', release),
        )

    # Build the helm command
    args = []
    if kubeconfig:
        args.extend(['--kubeconfig', kubeconfig])
    args.extend(['upgrade', '--install', '-n', namespace, release, p['chart']])
    args.extend(['--timeout', p['timeout']])

    for vf in (p['values_files'] or []):
        args.extend(['--values', vf])

    inline_path = None
    if p['values']:
        inline_path, err = _write_inline_values(p['values'])
        if err:
            module.fail_json(msg=err)
        args.extend(['--values', inline_path])

    try:
        for k, v in (p['set_values'] or {}).items():
            args.extend(['--set', '{0}={1}'.format(k, v)])
        for k, v in (p['set_string_values'] or {}).items():
            args.extend(['--set-string', '{0}={1}'.format(k, v)])
        for k, v in (p['set_file_values'] or {}).items():
            args.extend(['--set-file', '{0}={1}'.format(k, v)])

        if p['wait']:
            args.append('--wait')
        if p['atomic']:
            args.append('--atomic')
        if p['cleanup_on_fail']:
            args.append('--cleanup-on-fail')
        if p['force']:
            args.append('--force')
        if p['recreate_pods']:
            args.append('--recreate-pods')
        if p['create_namespace']:
            args.append('--create-namespace')
        if p['dependency_update']:
            args.append('--dependency-update')
        if p['reset_values']:
            args.append('--reset-values')
        if p['disable_hooks']:
            args.append('--no-hooks')
        if p['version']:
            args.extend(['--version', p['version']])
        if p['repo']:
            args.extend(['--repo', p['repo']])
        if p['description']:
            args.extend(['--description', p['description']])
        if p['debug']:
            args.append('--debug')

        rc, stdout, stderr = run_helm(args)
    finally:
        if inline_path and os.path.isfile(inline_path):
            try:
                os.unlink(inline_path)
            except OSError:
                pass

    after = _get_release_status(run_helm, namespace, release, kubeconfig=kubeconfig)
    after_revision = int(after.get('revision', 0)) if after else 0

    changed = (before is None) or (after_revision > before_revision)

    result = {
        'changed': changed,
        'release_name': release,
        'namespace': namespace,
        'chart': p['chart'],
        'stdout': stdout,
    }
    if after:
        result['status'] = after.get('status', '')
        result['revision'] = after_revision
        result['notes'] = after.get('notes', '')
        result['version'] = after.get('chart_version', p.get('version') or '')

    module.exit_json(**result)


if __name__ == '__main__':
    main()
