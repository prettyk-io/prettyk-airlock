# COS-173/178: policy для AppRole `cosmo-app` — rw secret/cosmo/* (kv-v2).
# Загружается: services/scripts/openbao-bootstrap.ps1 (bao policy write cosmo-app).

# kv-v2 данные: чтение/запись секретов.
path "secret/data/cosmo/*" {
  capabilities = ["create", "read", "update", "delete"]
}

# kv-v2 metadata: list/чтение метаданных (для kv list / soft-delete).
path "secret/metadata/cosmo/*" {
  capabilities = ["read", "list", "delete"]
}

path "secret/metadata/cosmo" {
  capabilities = ["read", "list"]
}
