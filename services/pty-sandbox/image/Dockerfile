# PTY-SANDBOX-1: sandbox-образ сессии (allowlist-инструменты; НЕ free-shell).
#
# Сессия стартует только объявленный инструмент:
#   docker run ... pty-sandbox-base:local <tool> [args]
# где <tool> ∈ /etc/sandbox/allowlist (entrypoint sandbox-run).
# Профиль изоляции (non-root/caps/ro-rootfs/network none/лимиты/TTL) задаёт
# sandbox-сервис при создании контейнера — COS-189 §5.
FROM alpine:3.20

RUN apk add --no-cache git grep findutils coreutils

# non-root (uid 1000); логин-шелл запрещён (nologin) — свободный shell недоступен.
RUN adduser -D -u 1000 -h /workspace -s /sbin/nologin sandbox

COPY allowlist /etc/sandbox/allowlist
COPY sandbox-run /usr/local/bin/sandbox-run
RUN chmod 0555 /usr/local/bin/sandbox-run \
 && chmod 0444 /etc/sandbox/allowlist

USER sandbox
WORKDIR /workspace

ENTRYPOINT ["/usr/local/bin/sandbox-run"]
