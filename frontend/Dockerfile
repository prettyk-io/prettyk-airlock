# Cosmoport 2.0 — Frontend build + nginx serve
# Multi-stage: Vite build (TypeScript) → nginx:alpine (serve SPA)
#
# Build:
#   docker build -f Dockerfile -t cosmo-frontend:local .
# Serve:
#   nginx on :80 → compose maps :5174. Same-origin edge (COS-094):
#   SPA + /api + /live /ready /health + SSE passthrough (no buffering).
#   Canonical external edge — Caddy :8180; this nginx is the SPA's own
#   front door for direct access (React fetches relative /api/v1/...).

# ── Stage 1: Vite build ────────────────────────────────────────────
FROM node:22-alpine AS build

WORKDIR /app

# Dependencies layer (cacheable)
COPY package.json package-lock.json ./
RUN npm ci

# Source
COPY . .

# Type-check + production build
RUN npm run build

# ── Stage 2: nginx serve SPA ───────────────────────────────────────
FROM nginx:alpine

# Копировать статику из build stage
COPY --from=build /app/dist /usr/share/nginx/html

# SPA fallback: все пути → index.html (React Router)
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]