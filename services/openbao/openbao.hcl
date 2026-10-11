# PrettyK Platform — OpenBao server config (dev-контур).
# Канон: D:\prettyk.io\void-core\OPENBAO-PLATFORM.md (§4 dev-топология).
#
# COS-178: persistent storage (raft) + static auto-unseal — AppRole `cosmo-app`
# и secret/cosmo/* переживают рестарт контейнера/хоста без ручных шагов.
#   - storage raft: persistent backend (file-backend deprecated с v2.7.0);
#   - seal static: auto-unseal без KMS (dev-профиль). Unseal key — 32-байтный
#     файл ВНЕ git: services/.openbao/unseal.key (создаётся
#     services/scripts/openbao-bootstrap.ps1, монтируется в /openbao/secrets).
#     Прод-профиль — KMS/HSM auto-unseal (канон §7).

ui = true
api_addr     = "http://127.0.0.1:8200"
cluster_addr = "http://127.0.0.1:8201"

storage "raft" {
  path = "/openbao/file"
}

listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = true
}

seal "static" {
  current_key_id = "dev-1"
  current_key    = "file:///openbao/secrets/unseal.key"
}
