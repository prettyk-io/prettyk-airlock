{{/*
Cosmoport 2.0 — shared template helpers.
*/}}

{{- define "cosmo.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "cosmo.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{- define "cosmo.labels" -}}
app.kubernetes.io/name: {{ include "cosmo.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: cosmoport
{{- end }}

{{- define "cosmo.selectorLabels" -}}
app.kubernetes.io/name: {{ include "cosmo.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Build DSN from values (keeps password out of templates).
DSN: postgresql+asyncpg://user:password@host:port/database
*/}}
{{- define "cosmo.pgDsn" -}}
postgresql+asyncpg://{{ .Values.postgres.user }}:$(PG_PASSWORD)@{{ .Values.postgres.host }}:{{ .Values.postgres.port }}/{{ .Values.postgres.database }}
{{- end }}