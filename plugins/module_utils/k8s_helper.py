#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Virtru
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Kubernetes helper utilities for virtru.dsp_platform modules."""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import base64
import json


class K8sHelper:
    """Helper for Kubernetes operations via kubectl CLI."""

    def __init__(self, runner, namespace='virtru'):
        self.runner = runner
        self.namespace = namespace

    def namespace_exists(self):
        """Check if the namespace exists."""
        rc, _, _ = self.runner.run_kubectl(
            ['get', 'namespace', self.namespace],
            check_rc=False,
        )
        return rc == 0

    def ensure_namespace(self):
        """Create namespace if it doesn't exist. Returns True if created."""
        if self.namespace_exists():
            return False
        self.runner.run_kubectl([
            'create', 'namespace', self.namespace,
        ])
        return True

    def secret_exists(self, name):
        """Check if a secret exists in the namespace."""
        rc, _, _ = self.runner.run_kubectl(
            ['get', 'secret', name, '-n', self.namespace],
            check_rc=False,
        )
        return rc == 0

    def create_secret_generic_idempotent(self, name, literals=None, from_files=None):
        """Create a secret using kubectl create --dry-run=client -o yaml | kubectl apply -f -.

        Uses a temp file to work around module.run_command() not supporting pipes.
        """
        import tempfile

        cmd = [
            self.runner.kubectl_bin,
            'create', 'secret', 'generic', name,
            '--namespace', self.namespace,
            '--dry-run=client', '-o', 'yaml',
        ]

        if literals:
            for key, value in literals.items():
                cmd.append('--from-literal={0}={1}'.format(key, value))

        if from_files:
            for key, filepath in from_files.items():
                cmd.append('--from-file={0}={1}'.format(key, filepath))

        rc, yaml_output, stderr = self.runner.run_command(cmd)

        # Write to temp file and apply
        tmpfile = tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False)
        try:
            tmpfile.write(yaml_output)
            tmpfile.close()
            self.runner.run_kubectl(['apply', '-f', tmpfile.name])
        finally:
            import os
            os.unlink(tmpfile.name)

        return True

    def create_tls_secret(self, name, cert_path, key_path):
        """Create a TLS secret idempotently."""
        if self.secret_exists(name):
            return False

        self.runner.run_kubectl([
            'create', 'secret', 'tls', name,
            '--cert', cert_path,
            '--key', key_path,
            '-n', self.namespace,
        ])
        return True

    def get_secret_value(self, secret_name, key):
        """Get a decoded value from a K8s secret."""
        rc, stdout, _ = self.runner.run_kubectl([
            'get', 'secret', secret_name,
            '-n', self.namespace,
            '-o', 'jsonpath={.data.' + key + '}',
        ], check_rc=False)

        if rc != 0 or not stdout.strip():
            return None

        return base64.b64decode(stdout.strip()).decode('utf-8')

    def get_pod_status(self, label_selector=None):
        """Get pod status summary for the namespace.

        Returns:
            Dict with keys: running, pending, failed, pods (list of details).
        """
        cmd = [
            'get', 'pods', '-n', self.namespace,
            '-o', 'json',
        ]
        if label_selector:
            cmd.extend(['-l', label_selector])

        result = self.runner.run_kubectl(cmd, parse_json=True)
        pods = result.get('items', [])

        status = {'running': 0, 'pending': 0, 'failed': 0, 'pods': []}
        for pod in pods:
            phase = pod.get('status', {}).get('phase', 'Unknown')
            name = pod.get('metadata', {}).get('name', 'unknown')
            status['pods'].append({'name': name, 'phase': phase})
            if phase == 'Running':
                status['running'] += 1
            elif phase == 'Pending':
                status['pending'] += 1
            elif phase in ('Failed', 'Error', 'CrashLoopBackOff'):
                status['failed'] += 1

        return status

    def wait_for_rollout(self, resource_type, name, timeout='10m'):
        """Wait for a deployment/statefulset rollout to complete."""
        self.runner.run_kubectl([
            'rollout', 'status', resource_type, name,
            '-n', self.namespace,
            '--timeout', timeout,
        ])

    def apply_manifest(self, manifest_content):
        """Apply a YAML manifest from string content."""
        import tempfile
        import os

        tmpfile = tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False)
        try:
            tmpfile.write(manifest_content)
            tmpfile.close()
            self.runner.run_kubectl([
                'apply', '-f', tmpfile.name, '-n', self.namespace,
            ])
        finally:
            os.unlink(tmpfile.name)

    def kubectl_exec(self, pod_name, command):
        """Execute a command inside a pod.

        Args:
            pod_name: Pod name.
            command: List of command args to run in the pod.

        Returns:
            Tuple of (rc, stdout, stderr).
        """
        cmd = [
            'exec', '-n', self.namespace, pod_name, '--',
        ] + command
        return self.runner.run_kubectl(cmd, check_rc=False)

    def scale_deployment(self, name, replicas):
        """Scale a deployment."""
        self.runner.run_kubectl([
            'scale', 'deployment', name,
            '--replicas', str(replicas),
            '-n', self.namespace,
        ])

    def resource_exists(self, resource_type, name):
        """Check if a K8s resource exists."""
        rc, _, _ = self.runner.run_kubectl(
            ['get', resource_type, name, '-n', self.namespace],
            check_rc=False,
        )
        return rc == 0
