# OWN-BUDDY-001: Nexus to Sfera to Kubernetes Delivery

**Date:** 2026-08-30T17:55:19.699824+00:00
**Status:** ACCEPTANCE READY
**Available providers:** 

---

## 1. Local OCI Distribution Smoke (dev)

**Provider:** local-oci
**Image:** distribution/distribution:3.2.0
**Compose:** docker-compose.registry.yml
**Host:** localhost:5100
**Docker:** cosmo-registry-zr:5000 (env var REGISTRY_ZR_ENDPOINT)
**Auth:** none (dev)
**Status:** Active

Smoke flow: health -> push -> manifest -> resolve digest -> pull -> check -> tags
Test: test_local_oci_smoke in test_int_registry_smoke.py

---

## 2. Real Nexus Smoke (staging)

**Provider:** nexus (Sonatype Nexus Repository)
**Protocol:** OCI Distribution Spec v1.1
**Endpoint:** NEXUS_REGISTRY_ENDPOINT env var
**Robot account:** NEXUS_ROBOT_USER env var
**Secret ref:** NEXUS_SECRET_REF env var
**Status:** Staging - requires endpoint

Smoke flow identical to local-oci (same OCI V2 protocol).
Test: test_nexus_smoke in test_int_registry_smoke.py

---

## 3. T1-Sfera Capability Boundary

**Provider:** t1_sfera
**Status:** UNKNOWN
**Capabilities:** 34 items
**Fake provider:** NO
**OCI V2 confirmed:** NO

- **unknown**: 34

---

## 4. Kubernetes Delivery

Files delivered:
- services/k8s/registry-pull-secret.yaml (dockerconfigjson)
- services/k8s/deployment-digest-example.yaml (deploy by @sha256)
- services/helm/cosmo/templates/registry-pull-secret.yaml
- services/helm/cosmo/templates/api-deployment.yaml (imagePullSecrets + digest)
- services/helm/cosmo/templates/frontend-deployment.yaml (imagePullSecrets + digest)
- services/helm/cosmo/values.yaml (registry section added)

**Helm registry values:** provider, endpoint, useDigest, pullZone.
**Digest deployment:** image@sha256:... (never latest).
**imagePullSecret:** kubernetes.io/dockerconfigjson, vault-backed.

---

## 5. Health / Evidence / GAP Mode

RegistryAuditTrail: immutable SHA-256 chain, verify_chain(), audit report.
GapModePolicy: only local-oci allowed; docker.io/ghcr.io/quay.io blocked.
All deployed to orchestrator/cosmo/adapters/registry_audit.py.

---

## 6. Caddy / Ports

- cosmo-caddy: 8080:80 (API + Frontend)
- cosmo-registry-proxy: 8180:8180 + 8088:8088 (registry only)
- 8080 NOT used for registry - belongs to main Caddy.

---

## 7. D: Paths

10/11 paths on D:. .venv, pip, npm, Playwright, CDP Chrome, OpenCode, Docker, Temp.
5 junctions confirmed: OpenCode share, OpenCode appdata, Playwright, CDP Chrome, Docker.
5 env vars confirmed: TEMP, TMP, PIP_CACHE_DIR, PLAYWRIGHT_BROWSERS_PATH, CDP_CHROME_PROFILE.
pagefile.sys: manual step (sysdm.cpl -> D:).

---

## 8. Glossary: What Is NOT What

| Name | Is | Is NOT |
|---|---|---|
| distribution:3.2.0 | local-oci dev smoke | Nexus / Artifactory |
| OciRegistry adapter | OCI V2 protocol for any provider | Nexus-specific code |
| T1-Sfera | UNKNOWN (34 capabilities) | Working integration |
| Artifactory | Not included | - |
| cosmo-registry-proxy | Caddy on 8180/8088 for registry | Main Caddy on 8080 |

---

*Generated: 2026-08-30T17:55:19.699824+00:00*