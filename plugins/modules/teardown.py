#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Virtru
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Ansible module to tear down a DSP deployment."""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: teardown
short_description: Remove a Virtru DSP deployment
description:
  - Reverses a deployment performed by C(virtru.dsp_platform.deploy_k3s).
  - Every removal step is opt-out via a boolean flag.
  - Supports check_mode - reports what would be removed without touching state.
  - Defaults remove the helm release and Kubernetes namespace (cascades to PVCs,
    secrets, and ingressroutes) but leave the local extract directory and
    registry images alone.
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
  remove_helm_release:
    description: Run C(helm uninstall) for the release.
    type: bool
    default: true
  remove_namespace:
    description:
      - Delete the Kubernetes namespace.
      - Cascades to all namespaced resources including PVCs.
    type: bool
    default: true
  remove_extract_dir:
    description: Delete the local bundle extract directory (destructive on host filesystem).
    type: bool
    default: false
  extract_dir:
    description: Path to the local bundle extract directory.
    type: path
    default: /opt/virtru
  remove_registry_images:
    description:
      - Best-effort removal of DSP images from the target registry.
      - Uses the OCI distribution API (C(DELETE /v2/{repo}/manifests/{tag})).
      - Many registries return 405 unless image deletion is explicitly enabled.
    type: bool
    default: false
  registry_url:
    description: Registry base URL (e.g. C(localhost:8888/virtru)). Required when C(remove_registry_images=true).
    type: str
  registry_insecure:
    description: Use HTTP instead of HTTPS when talking to the registry.
    type: bool
    default: true
  registry_images_file:
    description:
      - Path to a newline-delimited file listing C(repo:tag) entries to remove.
      - If absent, the module looks for C({extract_dir}/virtru-dsp-bundle/images.txt).
    type: path
  helm_bin:
    description: Path to helm.
    type: path
    default: helm
  kubectl_bin:
    description: Path to kubectl.
    type: path
    default: kubectl
  wait:
    description: Wait for resources to be fully removed.
    type: bool
    default: true
  timeout:
    description: Per-step timeout (e.g. C(5m)).
    type: str
    default: 5m
  force:
    description: Continue after individual step failures and report them.
    type: bool
    default: false
notes:
  - This module is destructive. Use C(check_mode) to dry-run first.
  - PVCs and other namespaced resources are removed by namespace deletion -
    they are not deleted individually.
seealso:
  - description: The dsp_deploy role performs the deployment this module reverses.
    link: https://github.com/gpa7407/ansible-dsp-platform/tree/main/roles/dsp_deploy
  - module: virtru.dsp_platform.verify
author:
  - Greg Paladin (@gpaladin)
'''

EXAMPLES = r'''
- name: Standard teardown (helm + namespace)
  virtru.dsp_platform.teardown:
    namespace: virtru

- name: Full nuke including host filesystem and registry
  virtru.dsp_platform.teardown:
    namespace: virtru
    remove_extract_dir: true
    remove_registry_images: true
    registry_url: localhost:8888/virtru
    registry_insecure: true

- name: Dry run
  virtru.dsp_platform.teardown:
    namespace: virtru
    remove_extract_dir: true
  check_mode: true
'''

RETURN = r'''
changed:
  description: True when at least one removal step actually removed something.
  type: bool
  returned: always
removed:
  description: Names of steps that actually removed something.
  type: list
  elements: str
  returned: always
skipped:
  description: Steps disabled or no-op.
  type: list
  elements: str
  returned: always
errors:
  description: Non-fatal errors (only populated when force=true).
  type: list
  elements: dict
  returned: always
'''

import json
import os
import shutil
import ssl

from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ansible.module_utils.basic import AnsibleModule


def _registry_delete_manifest(registry_url, image_ref, insecure):
    """Best-effort delete of an image manifest via OCI distribution API.

    image_ref is 'repo:tag' or 'repo@sha256:...'. registry_url may include a
    path component (the namespace) which is concatenated with repo.
    """
    scheme = 'http' if insecure else 'https'

    # Split registry_url into host and optional path
    if '/' in registry_url:
        host, _, ns_path = registry_url.partition('/')
        ns_path = ns_path.strip('/')
    else:
        host = registry_url
        ns_path = ''

    if '@' in image_ref:
        repo, reference = image_ref.rsplit('@', 1)
    elif ':' in image_ref:
        repo, reference = image_ref.rsplit(':', 1)
    else:
        repo, reference = image_ref, 'latest'

    full_repo = '{0}/{1}'.format(ns_path, repo) if ns_path else repo
    url = '{0}://{1}/v2/{2}/manifests/{3}'.format(scheme, host, full_repo, reference)

    ctx = ssl._create_unverified_context() if not insecure else None

    # GET the manifest to obtain its digest, then DELETE by digest.
    req = Request(url, method='GET', headers={
        'Accept': 'application/vnd.oci.image.manifest.v1+json,'
                  'application/vnd.docker.distribution.manifest.v2+json',
    })
    try:
        with urlopen(req, timeout=15, context=ctx) as resp:
            digest = resp.headers.get('Docker-Content-Digest')
    except (HTTPError, URLError, ssl.SSLError, OSError) as e:
        return False, "manifest GET failed: {0}".format(e)

    if not digest:
        return False, "manifest has no Docker-Content-Digest header"

    delete_url = '{0}://{1}/v2/{2}/manifests/{3}'.format(scheme, host, full_repo, digest)
    req = Request(delete_url, method='DELETE')
    try:
        with urlopen(req, timeout=15, context=ctx) as resp:
            return resp.status in (200, 202), "DELETE -> {0}".format(resp.status)
    except HTTPError as e:
        return False, "DELETE -> {0} {1}".format(e.code, e.reason)
    except (URLError, ssl.SSLError, OSError) as e:
        return False, "DELETE failed: {0}".format(e)


def _read_images_file(path):
    """Read a newline-delimited image list, skipping blanks and comments."""
    images = []
    try:
        with open(path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                images.append(line)
    except OSError:
        pass
    return images


def _release_exists(module, helm_bin, namespace, release):
    rc, _, _ = module.run_command(
        [helm_bin, 'status', release, '-n', namespace],
        check_rc=False,
    )
    return rc == 0


def _namespace_exists(module, kubectl_bin, namespace):
    rc, _, _ = module.run_command(
        [kubectl_bin, 'get', 'namespace', namespace],
        check_rc=False,
    )
    return rc == 0


def main():
    module = AnsibleModule(
        argument_spec=dict(
            namespace=dict(type='str', default='virtru'),
            helm_release=dict(type='str', default='dsp'),
            remove_helm_release=dict(type='bool', default=True),
            remove_namespace=dict(type='bool', default=True),
            remove_extract_dir=dict(type='bool', default=False),
            extract_dir=dict(type='path', default='/opt/virtru'),
            remove_registry_images=dict(type='bool', default=False),
            registry_url=dict(type='str'),
            registry_insecure=dict(type='bool', default=True),
            registry_images_file=dict(type='path'),
            helm_bin=dict(type='path', default='helm'),
            kubectl_bin=dict(type='path', default='kubectl'),
            wait=dict(type='bool', default=True),
            timeout=dict(type='str', default='5m'),
            force=dict(type='bool', default=False),
        ),
        required_if=[
            ('remove_registry_images', True, ['registry_url']),
        ],
        supports_check_mode=True,
    )

    p = module.params
    removed = []
    skipped = []
    errors = []
    check_mode = module.check_mode

    def record_error(step, msg):
        if p['force']:
            errors.append({'step': step, 'error': msg})
        else:
            module.fail_json(
                msg="Teardown step '{0}' failed: {1}".format(step, msg),
                step=step,
                removed=removed,
                skipped=skipped,
                errors=errors,
            )

    # ---- Helm release ----
    if p['remove_helm_release']:
        if _release_exists(module, p['helm_bin'], p['namespace'], p['helm_release']):
            if check_mode:
                removed.append('helm_release (would remove)')
            else:
                cmd = [p['helm_bin'], 'uninstall', p['helm_release'],
                       '-n', p['namespace']]
                if p['wait']:
                    cmd.extend(['--wait', '--timeout', p['timeout']])
                rc, stdout, stderr = module.run_command(cmd, check_rc=False)
                if rc != 0:
                    record_error('helm_release', stderr.strip() or stdout.strip())
                else:
                    removed.append('helm_release')
        else:
            skipped.append('helm_release (release not found)')
    else:
        skipped.append('helm_release (disabled)')

    # ---- Namespace + PVCs ----
    if p['remove_namespace']:
        if _namespace_exists(module, p['kubectl_bin'], p['namespace']):
            if check_mode:
                removed.append('namespace (would remove)')
            else:
                cmd = [p['kubectl_bin'], 'delete', 'namespace', p['namespace']]
                if p['wait']:
                    cmd.extend(['--wait=true', '--timeout', p['timeout']])
                else:
                    cmd.append('--wait=false')
                rc, stdout, stderr = module.run_command(cmd, check_rc=False)
                if rc != 0:
                    record_error('namespace', stderr.strip() or stdout.strip())
                else:
                    removed.append('namespace')
        else:
            skipped.append('namespace (not found)')
    else:
        skipped.append('namespace (disabled)')

    # ---- Local extract dir ----
    if p['remove_extract_dir']:
        if os.path.isdir(p['extract_dir']):
            if check_mode:
                removed.append('extract_dir (would remove)')
            else:
                try:
                    shutil.rmtree(p['extract_dir'])
                    removed.append('extract_dir')
                except OSError as e:
                    record_error('extract_dir', str(e))
        else:
            skipped.append('extract_dir (not found)')
    else:
        skipped.append('extract_dir (disabled)')

    # ---- Registry images ----
    if p['remove_registry_images']:
        images_file = p['registry_images_file']
        if not images_file:
            default_path = os.path.join(p['extract_dir'], 'virtru-dsp-bundle', 'images.txt')
            if os.path.isfile(default_path):
                images_file = default_path

        images = _read_images_file(images_file) if images_file else []
        if not images:
            skipped.append('registry_images (no images.txt found)')
        else:
            if check_mode:
                removed.append('registry_images (would remove {0})'.format(len(images)))
            else:
                deleted = 0
                failures = []
                for img in images:
                    ok, msg = _registry_delete_manifest(
                        p['registry_url'], img, p['registry_insecure'])
                    if ok:
                        deleted += 1
                    else:
                        failures.append('{0}: {1}'.format(img, msg))

                if deleted == 0:
                    record_error(
                        'registry_images',
                        'No images removed. Failures: {0}'.format('; '.join(failures[:5])),
                    )
                else:
                    label = 'registry_images ({0} of {1} removed)'.format(deleted, len(images))
                    if failures:
                        # Treat partial success as success unless force=false.
                        # Always include the count in `removed`.
                        if p['force']:
                            errors.append({
                                'step': 'registry_images',
                                'error': '; '.join(failures[:10]),
                            })
                    removed.append(label)
    else:
        skipped.append('registry_images (disabled)')

    changed = any('would remove' in r or not r.endswith(')') or '(' not in r
                  for r in removed) if removed else False
    # Simpler rule: changed iff anything ran (either real or in check_mode).
    changed = len(removed) > 0

    module.exit_json(
        changed=changed,
        removed=removed,
        skipped=skipped,
        errors=errors,
    )


if __name__ == '__main__':
    main()
