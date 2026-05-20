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
  - Extracts the DSP bundle tar.gz archive and locates tools (dsp, tructl, helm, grpcurl)
    for the target architecture.
  - Idempotent - skips extraction if the destination already contains expected files.
version_added: "1.0.0"
options:
  bundle_file:
    description: Path to the DSP bundle tar.gz file.
    type: path
    required: true
  dest:
    description: Directory to extract the bundle into.
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
- name: Extract DSP bundle
  virtru.dsp_platform.bundle_extract:
    bundle_file: /opt/virtru-dsp-bundle-v2.0.6.1.tar.gz
    dest: /opt/virtru

- name: Extract with explicit architecture
  virtru.dsp_platform.bundle_extract:
    bundle_file: /opt/bundle.tar.gz
    dest: /opt/virtru
    architecture: aarch64
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
  description: Path to the helm binary.
  type: str
  returned: always
chart_path:
  description: Path to the DSP Helm chart tgz.
  type: str
  returned: always
dsp_tag:
  description: Detected DSP version tag from the chart filename.
  type: str
  returned: always
'''

import glob
import os

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.virtru.dsp_platform.plugins.module_utils.dsp_common import (
    detect_architecture, find_tool_archive, extract_tool,
)


def main():
    module = AnsibleModule(
        argument_spec=dict(
            bundle_file=dict(type='path', required=True),
            dest=dict(type='path', required=True),
            tools_bin=dict(type='path'),
            architecture=dict(
                type='str',
                choices=['x86_64', 'aarch64', 'arm64', 'darwin_amd64', 'darwin_arm64'],
            ),
        ),
        supports_check_mode=True,
    )

    bundle_file = module.params['bundle_file']
    dest = module.params['dest']
    tools_bin = module.params.get('tools_bin') or os.path.join(dest, 'tools-bin')
    arch = module.params.get('architecture') or detect_architecture()

    # Validate bundle file exists
    if not os.path.isfile(bundle_file):
        module.fail_json(msg="Bundle file not found: {0}".format(bundle_file))

    # Check if already extracted by looking for the charts directory
    extracted_bundle = None
    for candidate in [
        os.path.join(dest, 'virtru-dsp-bundle'),
        dest,
    ]:
        if os.path.isdir(os.path.join(candidate, 'charts')):
            extracted_bundle = candidate
            break

    # Check if tools already extracted
    dsp_bin = os.path.join(tools_bin, 'dsp')
    tructl_bin = os.path.join(tools_bin, 'tructl')
    helm_bin = os.path.join(tools_bin, 'helm')

    already_extracted = (
        extracted_bundle is not None
        and os.path.isfile(dsp_bin)
        and os.path.isfile(tructl_bin)
        and os.path.isfile(helm_bin)
    )

    if already_extracted:
        # Find chart path
        chart_matches = glob.glob(os.path.join(extracted_bundle, 'charts', 'data-security-platform-*.tgz'))
        chart_path = chart_matches[0] if chart_matches else ''
        dsp_tag = ''
        if chart_path:
            # Extract version from chart filename: data-security-platform-2.0.6.1.tgz
            basename = os.path.basename(chart_path)
            version_part = basename.replace('data-security-platform-', '').replace('.tgz', '')
            dsp_tag = 'v{0}'.format(version_part)

        module.exit_json(
            changed=False,
            extracted_bundle=extracted_bundle,
            tools_bin=tools_bin,
            dsp_bin=dsp_bin,
            tructl_bin=tructl_bin,
            helm_bin=helm_bin,
            chart_path=chart_path,
            dsp_tag=dsp_tag,
        )

    if module.check_mode:
        module.exit_json(changed=True, msg="Would extract bundle")

    # Extract bundle
    os.makedirs(dest, exist_ok=True)
    os.makedirs(tools_bin, exist_ok=True)

    with tarfile.open(bundle_file, 'r:gz') as tar:
        tar.extractall(dest)

    # Locate the extracted bundle directory
    extracted_bundle = dest
    candidate = os.path.join(dest, 'virtru-dsp-bundle')
    if os.path.isdir(os.path.join(candidate, 'charts')):
        extracted_bundle = candidate

    if not os.path.isdir(os.path.join(extracted_bundle, 'charts')):
        module.fail_json(msg="Extracted bundle does not contain 'charts/' directory at {0}".format(extracted_bundle))

    # Extract DSP CLI tools
    dsp_tools_dir = os.path.join(extracted_bundle, 'tools', 'dsp')
    if os.path.isdir(dsp_tools_dir):
        dsp_archive = find_tool_archive(dsp_tools_dir, 'data-security-platform', arch)
        if dsp_archive:
            extract_tool(dsp_archive, tools_bin, ['dsp', 'tructl'])

    # Extract Helm
    helm_tools_dir = os.path.join(extracted_bundle, 'tools', 'helm')
    if os.path.isdir(helm_tools_dir):
        helm_archive = find_tool_archive(helm_tools_dir, 'helm', arch)
        if helm_archive:
            extract_tool(helm_archive, tools_bin, ['helm'])

    # Extract grpcurl
    grpcurl_tools_dir = os.path.join(extracted_bundle, 'tools', 'grpcurl')
    if os.path.isdir(grpcurl_tools_dir):
        grpcurl_archive = find_tool_archive(grpcurl_tools_dir, 'grpcurl', arch)
        if grpcurl_archive:
            extract_tool(grpcurl_archive, tools_bin, ['grpcurl'])

    # Verify critical tools were extracted
    if not os.path.isfile(dsp_bin):
        module.fail_json(msg="Failed to extract dsp binary to {0}".format(dsp_bin))
    if not os.path.isfile(tructl_bin):
        module.fail_json(msg="Failed to extract tructl binary to {0}".format(tructl_bin))

    # Find chart path
    chart_matches = glob.glob(os.path.join(extracted_bundle, 'charts', 'data-security-platform-*.tgz'))
    chart_path = chart_matches[0] if chart_matches else ''
    dsp_tag = ''
    if chart_path:
        basename = os.path.basename(chart_path)
        version_part = basename.replace('data-security-platform-', '').replace('.tgz', '')
        dsp_tag = 'v{0}'.format(version_part)

    grpcurl_path = os.path.join(tools_bin, 'grpcurl')

    module.exit_json(
        changed=True,
        extracted_bundle=extracted_bundle,
        tools_bin=tools_bin,
        dsp_bin=dsp_bin,
        tructl_bin=tructl_bin,
        helm_bin=helm_bin if os.path.isfile(helm_bin) else '',
        grpcurl_bin=grpcurl_path if os.path.isfile(grpcurl_path) else '',
        chart_path=chart_path,
        dsp_tag=dsp_tag,
    )


if __name__ == '__main__':
    main()
