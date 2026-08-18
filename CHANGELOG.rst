=====================================
DSP Platform Collection Release Notes
=====================================

.. contents:: Topics

v2.0.0
======

Release Summary
---------------

Major refactor for DSP 2.0.7+: the monolithic ``deploy_k3s`` module is replaced by the template-based ``dsp_deploy`` role, deployment targets an external Keycloak + PostgreSQL, and the Keycloak realm is provisioned natively via ``community.general.keycloak_*``. Validated against Keycloak 26.7 and PostgreSQL 18.

Major Changes
-------------

- dsp_deploy - Deploys against an EXTERNAL Keycloak + PostgreSQL only (embedded "playground" mode removed). The DSP realm/roles/clients and service-account role mappings are provisioned natively via the community.general.keycloak_* modules (DSP 2.0.7 removed `tructl provision`). Validated against Keycloak 26.7 and PostgreSQL 18.
- dsp_deploy - New role that replaces the deploy_k3s module. Deployment is now a sequence of small tasks that render Jinja2 templates (values.yaml, Traefik IngressRoute) and apply them with the kubernetes.core modules, instead of a monolithic module shelling out to sed/yq/kubectl/helm.

Minor Changes
-------------

- bundle_extract - bundle_file is now optional so the module works against an already-extracted (rsynced) bundle; dsp_tag is detected from the bundle's oci-artifacts image tag rather than the unrelated chart package version.

Breaking Changes / Porting Guide
--------------------------------

- The collection now depends on kubernetes.core, community.crypto, and community.general (see galaxy.yml).
- deploy_k3s - Removed; use the virtru.dsp_platform.dsp_deploy role.
- helm_deploy - Removed; use kubernetes.core.helm.

Bugfixes
--------

- bundle_extract - Import tarfile (the tarball extraction path previously raised NameError) and extract with the tar data filter to prevent path traversal.

v1.0.0
======

Release Summary
---------------

Initial release of the ``virtru.dsp_platform`` collection.

Major Changes
-------------

- bundle_extract - New module for extracting a DSP bundle and locating its CLI tools.
- copy_images - New module for pushing bundle container images to a target registry.
- deploy_k3s - New module for full DSP deployment on K3s (bundle extraction, image push, key generation, secrets, values.yaml, TLS, Helm install, Traefik ingress, Keycloak provisioning).
- helm_deploy - New module: full-featured helm upgrade/install/uninstall wrapper.
- keycloak_client - New module for full Keycloak client CRUD via kcadm.sh inside the Keycloak pod.
- teardown - New module for selective uninstall (helm release, namespace, extract dir, registry images).
- verify - New module for read-only post-deploy health checks (pods, helm, HTTP healthz, well-known, gRPC reflection, gRPC health, Keycloak realm).
- version_ge - New Jinja2 filter for semver-ish version comparisons.
