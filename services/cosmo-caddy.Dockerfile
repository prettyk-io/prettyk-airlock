# Cosmoport 2.0 — Custom Caddy build with rate_limit module (COS-067)
#
# Стандартный caddy:2.9-alpine НЕ включает http.handlers.rate_limit.
# Эта сборка добавляет модуль через xcaddy.
#
# Build:
#   docker build -f services/cosmo-caddy.Dockerfile -t cosmo-caddy:local services/
# Run:
#   docker compose up -d cosmo-caddy

# ── Stage 1: Build Caddy with rate_limit ──────────────────────────────
FROM caddy:2.9-builder-alpine AS builder

RUN xcaddy build \
    --with github.com/mholt/caddy-ratelimit

# ── Stage 2: Runtime ──────────────────────────────────────────────────
FROM caddy:2.9-alpine

COPY --from=builder /usr/bin/caddy /usr/bin/caddy

EXPOSE 80 443
CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile"]