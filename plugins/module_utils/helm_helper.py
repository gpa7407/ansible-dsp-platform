#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Virtru
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Helm helper utilities for virtru.dsp_platform modules."""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import json
import os


class HelmHelper:
    """Helper for Helm operations via helm CLI."""

    def __init__(self, runner, namespace='virtru', kubeconfig=None):
        self.runner = runner
        self.namespace = namespace
        self.kubeconfig = kubeconfig

    def _base_cmd(self):
        """Common flags prepended to every helm invocation."""
        cmd = []
        if self.kubeconfig:
            cmd.extend(['--kubeconfig', self.kubeconfig])
        return cmd

    def release_exists(self, release_name):
        """Check if a Helm release exists in the namespace."""
        rc, _, _ = self.runner.run_helm(
            self._base_cmd() + ['status', release_name, '-n', self.namespace],
            check_rc=False,
        )
        return rc == 0

    def get_release_status(self, release_name):
        """Get the status of a Helm release.

        Returns a dict with the helm-status JSON augmented with convenience
        keys (`chart`, `revision`, `status`, `notes`), or None if not found.
        """
        rc, stdout, _ = self.runner.run_helm(
            self._base_cmd() + ['status', release_name,
                                '-n', self.namespace,
                                '-o', 'json'],
            check_rc=False,
        )

        if rc != 0:
            return None

        try:
            data = json.loads(stdout)
        except (json.JSONDecodeError, ValueError):
            return None

        chart = data.get('chart', {})
        if isinstance(chart, dict):
            chart_name = '{0}-{1}'.format(
                chart.get('metadata', {}).get('name', ''),
                chart.get('metadata', {}).get('version', ''),
            ).strip('-')
            chart_version = chart.get('metadata', {}).get('version', '')
        else:
            chart_name = ''
            chart_version = ''

        info = data.get('info', {})
        data['chart_name'] = chart_name
        data['chart_version'] = chart_version
        data['revision'] = data.get('version', info.get('revision', 0))
        data['notes'] = info.get('notes', '')
        data['status'] = info.get('status', '')
        return data

    def get_revision(self, release_name):
        """Return the integer revision of an existing release, or 0 if absent."""
        status = self.get_release_status(release_name)
        if not status:
            return 0
        try:
            return int(status.get('revision', 0))
        except (TypeError, ValueError):
            return 0

    def upgrade_install(self, release_name, chart,
                        values_files=None,
                        values_inline=None,
                        set_values=None,
                        set_string_values=None,
                        set_file_values=None,
                        timeout='15m',
                        wait=True,
                        debug=False,
                        atomic=False,
                        cleanup_on_fail=False,
                        force=False,
                        recreate_pods=False,
                        create_namespace=False,
                        dependency_update=False,
                        reset_values=False,
                        disable_hooks=False,
                        version=None,
                        repo=None,
                        description=None):
        """Run helm upgrade --install with the full option surface.

        Args:
            release_name: Helm release name.
            chart: Path to chart (tgz, directory, or repo/chart reference).
            values_files: List of values file paths.
            values_inline: Path to a temp file holding inline values (caller
                writes the file; this method only appends `--values`).
            set_values: Dict of --set key=value.
            set_string_values: Dict of --set-string key=value.
            set_file_values: Dict of --set-file key=file_path.
            timeout: Timeout string (e.g., '15m').
            wait: Wait for resources to be ready.
            debug: Enable debug output.
            atomic: Roll back on failure.
            cleanup_on_fail: Clean up newly-created resources on failure.
            force: Force resource updates by replacement.
            recreate_pods: Recreate pods for the resources.
            create_namespace: Create the namespace if missing.
            dependency_update: Run dependency update before install.
            reset_values: Reset values to chart defaults.
            disable_hooks: Disable pre/post upgrade hooks.
            version: Pin chart version (when chart is a repo ref).
            repo: Chart repository URL (when chart is a name).
            description: Human-readable release description.

        Returns:
            Tuple of (rc, stdout, stderr).
        """
        cmd = self._base_cmd() + [
            'upgrade', '--install',
            '-n', self.namespace,
            release_name, chart,
            '--timeout', timeout,
        ]

        if values_files:
            for vf in values_files:
                cmd.extend(['--values', vf])

        if values_inline:
            cmd.extend(['--values', values_inline])

        if set_values:
            for key, value in set_values.items():
                cmd.extend(['--set', '{0}={1}'.format(key, value)])

        if set_string_values:
            for key, value in set_string_values.items():
                cmd.extend(['--set-string', '{0}={1}'.format(key, value)])

        if set_file_values:
            for key, value in set_file_values.items():
                cmd.extend(['--set-file', '{0}={1}'.format(key, value)])

        if wait:
            cmd.append('--wait')
        if debug:
            cmd.append('--debug')
        if atomic:
            cmd.append('--atomic')
        if cleanup_on_fail:
            cmd.append('--cleanup-on-fail')
        if force:
            cmd.append('--force')
        if recreate_pods:
            cmd.append('--recreate-pods')
        if create_namespace:
            cmd.append('--create-namespace')
        if dependency_update:
            cmd.append('--dependency-update')
        if reset_values:
            cmd.append('--reset-values')
        if disable_hooks:
            cmd.append('--no-hooks')
        if version:
            cmd.extend(['--version', version])
        if repo:
            cmd.extend(['--repo', repo])
        if description:
            cmd.extend(['--description', description])

        return self.runner.run_helm(cmd)

    def uninstall(self, release_name, wait=True, timeout='5m',
                  no_hooks=False, keep_history=False):
        """Uninstall a Helm release.

        Returns:
            True if uninstalled, False if release didn't exist.
        """
        if not self.release_exists(release_name):
            return False

        cmd = self._base_cmd() + ['uninstall', release_name, '-n', self.namespace]
        if wait:
            cmd.append('--wait')
            cmd.extend(['--timeout', timeout])
        if no_hooks:
            cmd.append('--no-hooks')
        if keep_history:
            cmd.append('--keep-history')

        self.runner.run_helm(cmd)
        return True

    def list_releases(self):
        """List all Helm releases in the namespace."""
        rc, stdout, _ = self.runner.run_helm(
            self._base_cmd() + ['list', '-n', self.namespace, '-o', 'json'],
            check_rc=False,
        )

        if rc != 0 or not stdout.strip():
            return []

        try:
            return json.loads(stdout)
        except (json.JSONDecodeError, ValueError):
            return []
