#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Virtru
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Ansible module to extract a DSP bundle and its tools."""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: bundle_extract
short_description: Extract a Virtru DSP bundle and tools
description:
  - Extracts the DSP bundle tar.gz archive (when supplied) and locates the CLI
    tools (dsp, tructl, helm, grpcurl) for the target architecture.
  - Also works against an already-extracted (e.g. rsynced) bundle - in that
    case C(bundle_file) may be omitted and only the tools are extracted.
  - Idempotent - skips work when the destination already contains the bundle
    and tool binaries.
version_added: "1.0.0"
options:
  bundle_file:
    description:
      - Path to the DSP bundle tar.gz file.
      - Optional when the bundle is already extracted under C(dest).
    type: path
  dest:
    description: Directory the bundle is (or will be) extracted into.
    type: path
    required: true
  tools_bin:
    description: Directory to place extracted tool binaries. Defaults to C(dest)/tools-bin.
    type: path
  architecture:
    description:
      - Target architecture for tool extraction.
      - Auto-detected if not specified.
    type: str
    choices: [x86_64, aarch64, arm64, darwin_amd64, darwin_arm64]
author:
  - Greg Paladin (@gpaladin)
'''

EXAMPLES = r'''
- name: Extract DSP bundle from a tarball
  virtru.dsp_platform.bundle_extract:
    bundle_file: /opt/virtru-dsp-bundle-v2.0.7.tar.gz
    dest: /opt/virtru

- name: Extract tools from an already-synced bundle
  virtru.dsp_platform.bundle_extract:
    dest: /opt/virtru
'''

RETURN = r'''
extracted_bundle:
  description: Path to the extracted bundle directory.
  type: str
  returned: always
tools_bin:
  description: Path to the tools binary directory.
  type: str
  returned: always
dsp_bin:
  description: Path to the dsp binary.
  type: str
  returned: always
tructl_bin:
  description: Path to the tructl binary.
  type: str
  returned: always
helm_bin:
  description: Path to the helm binary (empty string if not bundled).
  type: str
  returned: always
grpcurl_bin:
  description: Path to the grpcurl binary (empty string if not bundled).
  type: str
  returned: always
chart_path:
  description: Path to the DSP Helm chart tgz.
  type: str
  returned: always
dsp_tag:
  description:
    - Detected DSP application/image tag.
    - Read from C(oci-artifacts/data-security-platform/) (the shipped image tag)
      when available, falling back to the chart package version.
  type: str
  returned: always
'''

import glob
import os
import re
import tarfile

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.virtru.dsp_platform.plugins.module_utils.dsp_common import (
    detect_architecture, find_tool_archive, extract_tool,
)

# Matches a clean release tag like "v2.8.0" but not "v2.8.0-fips"/"-dev"/"-luna".
_CLEAN_TAG_RE = re.compile(r'^v\d+\.\d+(?:\.\d+){0,2}$')


def _locate_bundle(dest):
    """Return the bundle dir containing charts/, or None."""
    for candidate in (os.path.join(dest, 'virtru-dsp-bundle'), dest):
        if os.path.isdir(os.path.join(candidate, 'charts')):
            return candidate
    return None


def _find_chart(bundle_dir):
    matches = glob.glob(os.path.join(
        bundle_dir, 'charts', 'data-security-platform-*.tgz'))
    return matches[0] if matches else ''


def detect_dsp_tag(bundle_dir, chart_path):
    """Detect the DSP image tag.

    The chart *package* version (e.g. 0.11.1) is unrelated to the app/image
    tag (e.g. v2.8.0), so prefer the clean tag under oci-artifacts and only
    fall back to the chart filename when that is unavailable.
    """
    oci_dir = os.path.join(bundle_dir, 'oci-artifacts', 'data-security-platform')
    if os.path.isdir(oci_dir):
        clean = sorted(
            name for name in os.listdir(oci_dir)
            if _CLEAN_TAG_RE.match(name)
        )
        if clean:
            return clean[-1]

    if chart_path:
        version_part = os.path.basename(chart_path)
        version_part = version_part.replace('data-security-platform-', '')
        version_part = version_part.replace('.tgz', '')
        return 'v{0}'.format(version_part)

    return ''


def _extract_tools(bundle_dir, tools_bin, arch):
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


def main():
    module = AnsibleModule(
        argument_spec=dict(
            bundle_file=dict(type='path'),
            dest=dict(type='path', required=True),
            tools_bin=dict(type='path'),
            architecture=dict(
                type='str',
                choices=['x86_64', 'aarch64', 'arm64', 'darwin_amd64', 'darwin_arm64'],
            ),
        ),
        supports_check_mode=True,
    )

    bundle_file = module.params.get('bundle_file')
    dest = module.params['dest']
    tools_bin = module.params.get('tools_bin') or os.path.join(dest, 'tools-bin')
    arch = module.params.get('architecture') or detect_architecture()

    bundle_dir = _locate_bundle(dest)
    dsp_bin = os.path.join(tools_bin, 'dsp')
    tructl_bin = os.path.join(tools_bin, 'tructl')
    helm_bin = os.path.join(tools_bin, 'helm')
    grpcurl_bin = os.path.join(tools_bin, 'grpcurl')

    tools_present = os.path.isfile(dsp_bin) and os.path.isfile(tructl_bin)

    # Fast path: bundle and tools already in place.
    if bundle_dir and tools_present:
        chart_path = _find_chart(bundle_dir)
        module.exit_json(
            changed=False,
            extracted_bundle=bundle_dir,
            tools_bin=tools_bin,
            dsp_bin=dsp_bin,
            tructl_bin=tructl_bin,
            helm_bin=helm_bin if os.path.isfile(helm_bin) else '',
            grpcurl_bin=grpcurl_bin if os.path.isfile(grpcurl_bin) else '',
            chart_path=chart_path,
            dsp_tag=detect_dsp_tag(bundle_dir, chart_path),
        )

    # Need to do work. Validate we have something to work with.
    if not bundle_dir and not (bundle_file and os.path.isfile(bundle_file)):
        module.fail_json(
            msg="No extracted bundle found under {0} and no valid bundle_file "
                "provided.".format(dest)
        )

    if module.check_mode:
        module.exit_json(changed=True, msg="Would extract bundle and/or tools")

    os.makedirs(dest, exist_ok=True)
    os.makedirs(tools_bin, exist_ok=True)

    # Extract the tarball only when the bundle isn't already on disk.
    if not bundle_dir:
        with tarfile.open(bundle_file, 'r:gz') as tar:
            try:
                tar.extractall(dest, filter='data')  # py>=3.12: block path traversal
            except TypeError:
                tar.extractall(dest)  # older Python without the filter kwarg
        bundle_dir = _locate_bundle(dest)

    if not bundle_dir:
        module.fail_json(
            msg="Extracted bundle does not contain a 'charts/' directory under {0}".format(dest))

    _extract_tools(bundle_dir, tools_bin, arch)

    if not os.path.isfile(dsp_bin) or not os.path.isfile(tructl_bin):
        module.fail_json(
            msg="Failed to extract dsp/tructl binaries into {0}".format(tools_bin))

    chart_path = _find_chart(bundle_dir)
    module.exit_json(
        changed=True,
        extracted_bundle=bundle_dir,
        tools_bin=tools_bin,
        dsp_bin=dsp_bin,
        tructl_bin=tructl_bin,
        helm_bin=helm_bin if os.path.isfile(helm_bin) else '',
        grpcurl_bin=grpcurl_bin if os.path.isfile(grpcurl_bin) else '',
        chart_path=chart_path,
        dsp_tag=detect_dsp_tag(bundle_dir, chart_path),
    )


if __name__ == '__main__':
    main()
