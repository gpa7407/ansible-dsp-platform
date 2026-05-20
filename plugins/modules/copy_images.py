#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Virtru
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Ansible module to push DSP container images to a registry."""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: copy_images
short_description: Push DSP container images to a target registry
description:
  - Uses the C(dsp copy-images) CLI command to push all container images
    from an extracted DSP bundle to the target container registry.
  - Idempotent via a timestamp marker file.
version_added: "1.0.0"
options:
  dsp_bin:
    description: Path to the dsp CLI binary.
    type: path
    required: true
  registry_url:
    description:
      - Target registry URL (e.g., C(localhost:8888/virtru)).
    type: str
    required: true
  insecure:
    description: Use HTTP instead of HTTPS for the registry.
    type: bool
    default: true
  username:
    description: Registry username.
    type: str
  password:
    description: Registry password.
    type: str
    no_log: true
  extracted_bundle:
    description: Path to the extracted bundle directory. Used to check for freshness.
    type: path
author:
  - Greg Paladin (@gpaladin)
'''

EXAMPLES = r'''
- name: Push images to local K3s registry
  virtru.dsp_platform.copy_images:
    dsp_bin: /opt/virtru/tools-bin/dsp
    registry_url: localhost:8888/virtru
    insecure: true
'''

RETURN = r'''
registry_url:
  description: The registry URL images were pushed to.
  type: str
  returned: always
'''

import os
import time

from ansible.module_utils.basic import AnsibleModule


def main():
    module = AnsibleModule(
        argument_spec=dict(
            dsp_bin=dict(type='path', required=True),
            registry_url=dict(type='str', required=True),
            insecure=dict(type='bool', default=True),
            username=dict(type='str'),
            password=dict(type='str', no_log=True),
            extracted_bundle=dict(type='path'),
        ),
        supports_check_mode=True,
    )

    dsp_bin = module.params['dsp_bin']
    registry_url = module.params['registry_url']
    insecure = module.params['insecure']
    username = module.params.get('username')
    password = module.params.get('password')
    extracted_bundle = module.params.get('extracted_bundle')

    if not os.path.isfile(dsp_bin):
        module.fail_json(msg="dsp binary not found: {0}".format(dsp_bin))

    # Check idempotency via marker file
    marker_dir = extracted_bundle or os.path.dirname(dsp_bin)
    marker_file = os.path.join(marker_dir, '.images-pushed')

    if os.path.isfile(marker_file):
        # Check if bundle is newer than marker
        if extracted_bundle:
            bundle_mtime = os.path.getmtime(extracted_bundle)
            marker_mtime = os.path.getmtime(marker_file)
            if marker_mtime >= bundle_mtime:
                module.exit_json(
                    changed=False,
                    registry_url=registry_url,
                    msg="Images already pushed (marker file newer than bundle)",
                )
        else:
            module.exit_json(
                changed=False,
                registry_url=registry_url,
                msg="Images already pushed (marker file exists)",
            )

    if module.check_mode:
        module.exit_json(changed=True, msg="Would push images to {0}".format(registry_url))

    # Build command
    cmd = [dsp_bin, 'copy-images', registry_url]

    if insecure:
        cmd.append('--insecure')

    if username:
        cmd.extend(['--username', username])

    if password:
        cmd.extend(['--password', password])

    rc, stdout, stderr = module.run_command(cmd, cwd=extracted_bundle)

    if rc != 0:
        module.fail_json(
            msg="Failed to push images to registry",
            cmd=' '.join(cmd),
            rc=rc,
            stdout=stdout,
            stderr=stderr,
        )

    # Write marker file
    with open(marker_file, 'w') as f:
        f.write(str(time.time()))

    module.exit_json(
        changed=True,
        registry_url=registry_url,
        stdout=stdout,
    )


if __name__ == '__main__':
    main()
