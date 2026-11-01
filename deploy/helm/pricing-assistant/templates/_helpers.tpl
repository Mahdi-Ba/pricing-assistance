{{- define "pa.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "pa.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name (include "pa.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "pa.labels" -}}
app.kubernetes.io/name: {{ include "pa.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{/* selector labels for one role: (dict "root" $ "role" "api") */}}
{{- define "pa.selector" -}}
app.kubernetes.io/name: {{ include "pa.name" .root }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .role | kebabcase }}
{{- end -}}

{{- define "pa.serviceAccount" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "pa.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{/* roles rendered for the chosen topology */}}
{{- define "pa.roles" -}}
{{- if eq .Values.topology "collectors" -}}
workerCollect workerBrowser
{{- else -}}
api scheduler workerProcess workerCollect workerBrowser web
{{- end -}}
{{- end -}}

{{- define "pa.isWorker" -}}
{{- if hasPrefix "worker" . }}true{{ end -}}
{{- end -}}

{{/* image for a role */}}
{{- define "pa.image" -}}
{{- $img := .root.Values.image.backend -}}
{{- if eq .role "workerBrowser" }}{{ $img = .root.Values.image.browser }}{{ end -}}
{{- if eq .role "web" }}{{ $img = .root.Values.image.web }}{{ end -}}
image: "{{ $img.repository }}:{{ $img.tag }}"
imagePullPolicy: {{ $img.pullPolicy }}
{{- end -}}

{{/* container command for a role */}}
{{- define "pa.command" -}}
{{- $cfg := index .root.Values.roles .role -}}
{{- if eq .role "api" -}}
command: ["uvicorn", "--factory", "pricing_assistant.app:create_app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
{{- else if eq .role "scheduler" -}}
command: ["python", "-m", "pricing_assistant.scheduler"]
{{- else if eq .role "web" -}}
command: ["node", "server.js"]
{{- else -}}
command: ["dramatiq", "pricing_assistant.workers", "--queues", {{ range $i, $q := $cfg.queues }}{{ if $i }}, {{ end }}{{ $q | quote }}{{ end }}, "--processes", "1", "--threads", {{ $cfg.threads | toString | quote }}]
{{- end -}}
{{- end -}}

{{/* backend environment for a role: config map, secrets, metrics port, optional mTLS material.
     Called with (dict "root" $ "role" "scheduler") */}}
{{- define "pa.backendEnv" -}}
{{- $v := .root.Values -}}
envFrom:
  - configMapRef:
      name: {{ include "pa.fullname" .root }}-backend
  - secretRef:
      name: {{ $v.secrets.backend }}
env:
  - name: PA_METRICS_PORT
    value: {{ if and $v.metrics.enabled (include "pa.hasMetricsPort" .role) }}{{ $v.metrics.port | toString | quote }}{{ else }}"0"{{ end }}
{{- if $v.tls.enabled }}
  - name: PGSSLMODE
    value: verify-full
  - name: PGSSLROOTCERT
    value: {{ $v.tls.mountPath }}/ca.crt
  - name: PGSSLCERT
    value: {{ $v.tls.mountPath }}/tls.crt
  - name: PGSSLKEY
    value: {{ $v.tls.mountPath }}/tls.key
  - name: PA_S3_CA_BUNDLE
    value: {{ $v.tls.mountPath }}/ca.crt
  - name: PA_S3_CLIENT_CERT
    value: {{ $v.tls.mountPath }}/tls.crt
  - name: PA_S3_CLIENT_KEY
    value: {{ $v.tls.mountPath }}/tls.key
{{- end }}
{{- end -}}

{{/* roles without their own HTTP server, which serve /metrics on metrics.port */}}
{{- define "pa.hasMetricsPort" -}}
{{- if or (eq . "scheduler") (hasPrefix "worker" .) }}true{{ end -}}
{{- end -}}

{{- define "pa.podSecurity" -}}
securityContext:
  {{- toYaml .Values.podSecurityContext | nindent 2 }}
{{- end -}}
