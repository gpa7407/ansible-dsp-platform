# keycloak_client

Manage Keycloak clients on the DSP-embedded Keycloak.

## Synopsis

- Creates, updates, and deletes Keycloak clients on the Keycloak instance deployed alongside DSP.
- Talks to Keycloak via `kcadm.sh` executed inside the Keycloak pod with `kubectl exec` (air-gapped-friendly).
- Idempotent - existing clients are updated in place; missing clients are created; clients in state `absent` are deleted only if present.
- Returns the client secret on creation or when `regenerate_secret` is true.

## Parameters

| Parameter | Type | Required | Default | Description |
| --------- | ---- | -------- | ------- | ----------- |
| `realm` | str | yes | | Keycloak realm name. |
| `state` | str | no | `present` | `present` ensures the client exists; `absent` deletes it. |
| `client_id` | str | yes | | Keycloak clientId (the human-readable identifier). |
| `name` | str | no | | Display name. |
| `description` | str | no | | Free-text description. |
| `enabled` | bool | no | `true` | Whether the client is enabled. |
| `public_client` | bool | no | `false` | If true, the client is public (no secret). |
| `client_authenticator_type` | str | no | `client-secret` | Client authentication method. |
| `standard_flow_enabled` | bool | no | `true` | Enable OAuth 2.0 authorization-code flow. |
| `direct_access_grants_enabled` | bool | no | `true` | Enable resource-owner password credentials flow. |
| `implicit_flow_enabled` | bool | no | `false` | Enable OAuth 2.0 implicit flow. |
| `service_accounts_enabled` | bool | no | `false` | Enable service-account flow (client_credentials grant). |
| `secret` | str | no | | Explicit client secret value (confidential clients only). |
| `redirect_uris` | list(str) | no | | List of allowed redirect URIs. |
| `web_origins` | list(str) | no | | List of allowed CORS origins. |
| `protocol` | str | no | `openid-connect` | Protocol (`openid-connect` or `saml`). |
| `attributes` | dict | no | | Free-form client attributes dict. |
| `service_account_realm_roles` | list(str) | no | | Realm roles to assign to the service account. |

## Notes

- Uses `kubectl exec` to run `kcadm.sh` inside the Keycloak pod, so `kubectl` must be configured.
- The Keycloak admin endpoint does not need to be exposed to the Ansible controller.

## Examples

```yaml
- name: Create a confidential OIDC client
  virtru.dsp_platform.keycloak_client:
    realm: opentdf
    client_id: my-service
    service_accounts_enabled: true
    redirect_uris:
      - "https://app.example.com/*"

- name: Create a public client for browser login
  virtru.dsp_platform.keycloak_client:
    realm: opentdf
    client_id: my-spa
    public_client: true
    redirect_uris:
      - "https://app.example.com/*"
    web_origins:
      - "https://app.example.com"

- name: Delete a client
  virtru.dsp_platform.keycloak_client:
    realm: opentdf
    client_id: old-client
    state: absent
```

## Return Values

| Key | Type | Returned | Description |
| --- | ---- | -------- | ----------- |
| `client_id` | str | success | The clientId of the managed client. |
| `client_secret` | str | when created or regenerated | The client secret (confidential clients only). |

## See Also

- [deploy_k3s](deploy_k3s.md) - Deploy DSP on K3s
