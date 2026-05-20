#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Virtru
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Shared helper utilities for virtru.dsp_platform Ansible modules."""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import glob
import json
import os
import platform as _platform
import tarfile
import time


def common_argument_spec():
    """Return argument spec shared by all platform modules."""
    return dict(
        dsp_bin=dict(type='path'),
        tructl_bin=dict(type='path'),
        helm_bin=dict(type='path'),
        kubectl_bin=dict(type='path', default='kubectl'),
        grpcurl_bin=dict(type='path'),
    )


def version_ge(version_a, version_b):
    """Compare two semver-ish version strings (e.g., 'v2.6.1' >= 'v2.6').

    Strips leading 'v' and compares numeric parts left to right.
    Returns True if version_a >= version_b.
    """
    def parse(v):
        return [int(x) for x in v.lstrip('v').split('.')]

    try:
        a_parts = parse(version_a)
        b_parts = parse(version_b)
    except (ValueError, AttributeError):
        return False

    # Pad shorter list with zeros
    max_len = max(len(a_parts), len(b_parts))
    a_parts.extend([0] * (max_len - len(a_parts)))
    b_parts.extend([0] * (max_len - len(b_parts)))

    return a_parts >= b_parts


class DspRunner:
    """Helper class for executing CLI commands via Ansible module.run_command().

    Wraps dsp, tructl, helm, kubectl, and grpcurl CLI invocations.
    """

    # Standard K3s kubeconfig location
    K3S_KUBECONFIG = '/etc/rancher/k3s/k3s.yaml'

    def __init__(self, module):
        self.module = module
        self.dsp_bin = module.params.get('dsp_bin') or 'dsp'
        self.tructl_bin = module.params.get('tructl_bin') or 'tructl'
        self.helm_bin = module.params.get('helm_bin') or 'helm'
        self.kubectl_bin = module.params.get('kubectl_bin') or 'kubectl'
        self.grpcurl_bin = module.params.get('grpcurl_bin') or 'grpcurl'
        self._phases = []

        # Auto-detect KUBECONFIG for K3s if not already set
        if not os.environ.get('KUBECONFIG') and os.path.isfile(self.K3S_KUBECONFIG):
            os.environ['KUBECONFIG'] = self.K3S_KUBECONFIG

    def run_command(self, cmd, check_rc=True, parse_json=False, cwd=None,
                    environ_update=None):
        """Execute a command.

        Args:
            cmd: List of command arguments including the binary.
            check_rc: If True, fail the module on non-zero return code.
            parse_json: If True, parse stdout as JSON.
            cwd: Working directory for the command.
            environ_update: Dict of env vars to add/override for this command
                (passed through to AnsibleModule.run_command). Use this to
                inject secrets like C(COSIGN_PASSWORD) without persisting them.

        Returns:
            Tuple of (rc, stdout, stderr) if not parse_json,
            otherwise parsed JSON object.
        """
        rc, stdout, stderr = self.module.run_command(
            cmd, cwd=cwd, environ_update=environ_update,
        )

        if check_rc and rc != 0:
            self.module.fail_json(
                msg="Command failed",
                cmd=' '.join(cmd),
                rc=rc,
                stdout=stdout,
                stderr=stderr,
                phases_completed=self._phases,
            )

        if parse_json and stdout.strip():
            try:
                return json.loads(stdout)
            except (json.JSONDecodeError, ValueError):
                self.module.fail_json(
                    msg="Failed to parse JSON output",
                    cmd=' '.join(cmd),
                    stdout=stdout,
                    stderr=stderr,
                )

        if parse_json:
            return {}

        return rc, stdout, stderr

    def run_dsp(self, args, check_rc=True, parse_json=False, cwd=None):
        """Execute a dsp CLI command."""
        cmd = [self.dsp_bin] + args
        return self.run_command(cmd, check_rc=check_rc, parse_json=parse_json, cwd=cwd)

    def run_tructl(self, args, host=None, tls_no_verify=True, client_creds=None,
                   check_rc=True, parse_json=False):
        """Execute a tructl CLI command with optional global flags."""
        cmd = [self.tructl_bin]
        if host:
            cmd.extend(['--host', host])
        if tls_no_verify:
            cmd.append('--tls-no-verify')
        if client_creds:
            cmd.extend(['--with-client-creds', json.dumps(client_creds)])
        cmd.extend(args)
        return self.run_command(cmd, check_rc=check_rc, parse_json=parse_json)

    def run_helm(self, args, check_rc=True, cwd=None):
        """Execute a helm command."""
        cmd = [self.helm_bin] + args
        return self.run_command(cmd, check_rc=check_rc, cwd=cwd)

    def run_kubectl(self, args, check_rc=True, parse_json=False):
        """Execute a kubectl command."""
        cmd = [self.kubectl_bin] + args
        return self.run_command(cmd, check_rc=check_rc, parse_json=parse_json)

    def log_phase(self, name, status='completed'):
        """Record a phase completion for structured output."""
        self._phases.append(name)

    @property
    def phases_completed(self):
        """Return list of completed phases."""
        return list(self._phases)

    def file_exists(self, path):
        """Check if a file exists."""
        return os.path.isfile(path)

    def dir_exists(self, path):
        """Check if a directory exists."""
        return os.path.isdir(path)

    def ensure_dir(self, path):
        """Create directory if it doesn't exist."""
        if not os.path.isdir(path):
            os.makedirs(path, exist_ok=True)


# ---- Bundle / tool extraction helpers ----

def detect_architecture():
    """Detect system architecture for tool selection."""
    machine = _platform.machine().lower()
    system = _platform.system().lower()

    if system == 'darwin':
        if machine in ('arm64', 'aarch64'):
            return 'darwin_arm64'
        return 'darwin_amd64'

    if machine in ('x86_64', 'amd64'):
        return 'x86_64'
    if machine in ('aarch64', 'arm64'):
        return 'aarch64'

    return machine


def find_tool_archive(tools_dir, tool_prefix, arch_hint):
    """Find a tool archive matching the architecture."""
    arch_patterns = {
        'x86_64': ['linux_amd64', 'linux-amd64', 'x86_64'],
        'aarch64': ['linux_arm64', 'linux-arm64', 'aarch64'],
        'arm64': ['linux_arm64', 'linux-arm64', 'arm64'],
        'darwin_amd64': ['darwin_amd64', 'darwin-amd64'],
        'darwin_arm64': ['darwin_arm64', 'darwin-arm64'],
    }

    patterns = arch_patterns.get(arch_hint, [arch_hint])

    for pattern in patterns:
        matches = glob.glob(os.path.join(tools_dir, '{0}*{1}*'.format(tool_prefix, pattern)))
        # Filter out signature files, checksums, and SBOMs
        matches = [m for m in matches
                   if not m.endswith(('.sig', '.txt', '.json', '.sha256sum', '.sha256'))]
        if matches:
            return matches[0]

    return None


def extract_tool(archive_path, dest_dir, binary_names):
    """Extract specific binaries from a tool archive.

    Returns list of extracted file paths.
    """
    extracted = []

    if archive_path.endswith('.tar.gz') or archive_path.endswith('.tgz'):
        with tarfile.open(archive_path, 'r:gz') as tar:
            for member in tar.getmembers():
                basename = os.path.basename(member.name)
                if basename in binary_names and member.isfile():
                    member.name = basename
                    tar.extract(member, dest_dir)
                    dest_path = os.path.join(dest_dir, basename)
                    os.chmod(dest_path, 0o755)
                    extracted.append(dest_path)

    return extracted
