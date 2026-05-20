===================================
DSP Platform Collection Change Log
===================================

.. contents:: Topics

v1.0.0
======

Release Summary
---------------

Initial release of the ``virtru.dsp_platform`` collection.

Major Changes
-------------

- deploy_k3s - New module for full DSP deployment on K3s (bundle extraction, image push, key generation, secrets, values.yaml, TLS, Helm install, Traefik ingress, Keycloak provisioning).
- verify - New module for read-only post-deploy health checks (pods, helm, HTTP healthz, well-known, gRPC reflection, gRPC health, Keycloak realm).
- teardown - New module for selective uninstall (helm release, namespace, extract dir, registry images).
- keycloak_client - New module for full Keycloak client CRUD via kcadm.sh inside the Keycloak pod.
- helm_deploy - New module: full-featured helm upgrade/install/uninstall wrapper.
- bundle_extract - New module for extracting a DSP bundle and locating its CLI tools.
- copy_images - New module for pushing bundle container images to a target registry.
- version_ge - New Jinja2 filter for semver-ish version comparisons.
