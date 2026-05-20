#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Virtru
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Custom Jinja2 filters for virtru.dsp_platform collection."""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
name: version_ge
short_description: Compare two semver-ish version strings (a >= b)
description:
  - Returns True when C(version_a) is greater than or equal to C(version_b).
  - Leading C(v) is stripped before comparison and shorter version lists are
    zero-padded so C(v2.6 >= v2.6.0) holds.
version_added: "1.0.0"
options:
  _input:
    description: The reference version (left operand).
    type: str
    required: true
  other:
    description: The version to compare against (right operand).
    type: str
    required: true
author:
  - Greg Paladin (@gpaladin)
'''

EXAMPLES = r'''
- name: Gate v2.6+ tweaks
  ansible.builtin.set_fact:
    needs_pprof_settings: "{{ dsp_tag | virtru.dsp_platform.version_ge('v2.6') }}"
'''

RETURN = r'''
_value:
  description: True when C(_input >= other).
  type: bool
'''


def version_ge(version_a, version_b):
    """Compare two semver-ish version strings.

    Returns True if version_a >= version_b.
    Usage in Jinja2: {{ dsp_tag | virtru.dsp_platform.version_ge('v2.6') }}
    """
    def parse(v):
        return [int(x) for x in str(v).lstrip('v').split('.')]

    try:
        a_parts = parse(version_a)
        b_parts = parse(version_b)
    except (ValueError, AttributeError):
        return False

    max_len = max(len(a_parts), len(b_parts))
    a_parts.extend([0] * (max_len - len(a_parts)))
    b_parts.extend([0] * (max_len - len(b_parts)))

    return a_parts >= b_parts


class FilterModule:
    """DSP platform filter plugins."""

    def filters(self):
        return {
            'version_ge': version_ge,
        }
