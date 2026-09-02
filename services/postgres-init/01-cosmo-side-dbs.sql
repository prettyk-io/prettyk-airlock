-- COS-063: side databases for full delivery profile.
-- Runs only on an EMPTY postgres volume (docker-entrypoint-initdb.d).
CREATE DATABASE cosmo_gitea OWNER cosmo;
CREATE DATABASE cosmo_woodpecker OWNER cosmo;
