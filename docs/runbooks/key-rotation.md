# Key rotation (connector secrets)

Connector secrets (for example API keys of a source) are encrypted in the database with AES-256-GCM. `PA_SECRET_ENCRYPTION_KEYS` holds versioned keys as `version:base64key,...`. The **highest** version encrypts; every listed version can decrypt. Each stored secret records the key version it was encrypted with.

**Rotate on a schedule, and immediately on a suspected leak.**

1. **Generate** a new 32-byte key:
   ```bash
   python3 -c "import os,base64; print(base64.b64encode(os.urandom(32)).decode())"
   ```
2. **Add** it as the next version, keeping the old one, in the secret store (for example `1:OLDKEY,2:NEWKEY`). Let External Secrets sync, then restart all backend pods so every process loads the new set:
   ```bash
   oc -n $NS rollout restart deploy -l app.kubernetes.io/instance=pa
   ```
   New and changed secrets are now encrypted with version 2.
3. **Re-encrypt** existing secrets by writing them again (the values come from the source owners or your vault):
   ```bash
   curl -s -X PUT -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"value":"<secret value>"}' "$API/api/v1/sources/<id>/secrets/<name>"
   ```
4. **Check** that nothing still uses the old version (per tenant):
   ```sql
   SELECT key_version, count(*) FROM connector_secret GROUP BY key_version;
   ```
5. **Remove** the old key from `PA_SECRET_ENCRYPTION_KEYS` only when step 4 shows no rows with it, then restart the pods again. A secret still encrypted with a removed key can no longer be decrypted; the connector reports a configuration error until the secret is written again.

On a leak, also rotate the leaked connector credentials at the source itself. Re-encrypting does not invalidate a credential that has already leaked.
