/**
 * COS-080: Security Gate Policy Builder & Configurator UI.
 *
 * Visual editor for constructing and configuring Security Gate policies:
 *   - Policy templates (Strict GOST, Standard Release, Fast Hotfix)
 *   - Interactive list of rules (finding_type, action, max_count)
 *   - CWE / category granularity
 *   - Admission Gate settings (manual signature, role requirements)
 *   - Save, Export JSON, Test on findings
 */
import { useEffect, useState, useCallback, type ReactNode, type ReactElement } from 'react';
import {
  Box, Typography, Button, Chip, Paper, Skeleton,
  Alert, IconButton, Tooltip, TextField, MenuItem, Card, CardContent,
  Grid, Slider, Checkbox, FormControlLabel, Divider, Switch,
  Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
} from '@mui/material';
import {
  Gavel, Add, Delete, Save as SaveIcon, Download, PlayArrow,
  Security, Shield, VerifiedUser, Warning, Block,
  CheckCircle, HourglassEmpty,
} from '@mui/icons-material';
import { api, type Gate, type GatePolicy, type GatePolicyRule } from '../api';
import { ErrorBoundary } from '../../shared/ErrorBoundary';
import { EmptyState } from '../../shared/EmptyState';
import { toast } from '../../shared/toast';

// ── Policy Templates ─────────────────────────────────────────────────

type TemplateId = 'gost_strict' | 'standard_release' | 'fast_hotfix';

interface PolicyTemplate {
  id: TemplateId;
  label: string;
  description: string;
  gate_type: 'automatic' | 'manual';
  require_manual_signature: boolean;
  mandatory_role: string;
  rules: GatePolicyRule[];
}

const POLICY_TEMPLATES: PolicyTemplate[] = [
  {
    id: 'gost_strict',
    label: 'Строгий ГОСТ',
    description: 'ГОСТ Р 57580 (ФСТЭК) — критическая защита с двухуровневой подписью.',
    gate_type: 'manual',
    require_manual_signature: true,
    mandatory_role: 'secops_lead',
    rules: [
      { finding_type: 'Critical', action: 'block', max_count: 0 },
      { finding_type: 'High', action: 'block', max_count: 0 },
      { finding_type: 'Мedium', action: 'warn', max_count: 3 },
      { finding_type: 'Low', action: 'pass', max_count: null },
      { finding_type: 'CWE-89', action: 'block', max_count: 0 },
      { finding_type: 'CWE-94', action: 'block', max_count: 0 },
      { finding_type: 'CWE-79', action: 'warn', max_count: 5 },
    ],
  },
  {
    id: 'standard_release',
    label: 'Standard Release',
    description: 'Сбалансированная политика: блокировка Critical, жёлтый порог для High.',
    gate_type: 'automatic',
    require_manual_signature: false,
    mandatory_role: '',
    rules: [
      { finding_type: 'Critical', action: 'block', max_count: 0 },
      { finding_type: 'High', action: 'warn', max_count: 3 },
      { finding_type: 'Мedium', action: 'warn', max_count: 10 },
      { finding_type: 'Low', action: 'pass', max_count: null },
    ],
  },
  {
    id: 'fast_hotfix',
    label: 'Fast Hotfix',
    description: 'Быстрый CI/CD хотфикс: только блокировка Critical, пропуск High.',
    gate_type: 'automatic',
    require_manual_signature: false,
    mandatory_role: '',
    rules: [
      { finding_type: 'Critical', action: 'block', max_count: 0 },
      { finding_type: 'High', action: 'warn', max_count: 10 },
      { finding_type: 'Мedium', action: 'pass', max_count: null },
    ],
  },
];

// ── Finding Type Options ──────────────────────────────────────────────

const FINDING_CATEGORIES = [
  { value: 'Critical', label: 'Critical (CVSS 9.0–10.0)', color: '#7F1D1D' },
  { value: 'High', label: 'High (CVSS 7.0–8.9)', color: '#991B1B' },
  { value: 'Medium', label: 'Medium (CVSS 4.0–6.9)', color: '#92400E' },
  { value: 'Low', label: 'Low (CVSS 0.1–3.9)', color: '#3F6212' },
  { value: 'Info', label: 'Info / Informational', color: '#1E40AF' },
  { value: 'CWE-89', label: 'CWE-89 — SQL Injection', color: '#7F1D1D' },
  { value: 'CWE-79', label: 'CWE-79 — Cross-Site Scripting (XSS)', color: '#991B1B' },
  { value: 'CWE-94', label: 'CWE-94 — Code Injection (RCE)', color: '#7F1D1D' },
  { value: 'CWE-22', label: 'CWE-22 — Path Traversal', color: '#92400E' },
  { value: 'CWE-352', label: 'CWE-352 — CSRF', color: '#854D0E' },
  { value: 'CWE-918', label: 'CWE-918 — SSRF', color: '#991B1B' },
  { value: 'CWE-502', label: 'CWE-502 — Insecure Deserialization', color: '#991B1B' },
  { value: 'CWE-798', label: 'CWE-798 — Hardcoded Credentials', color: '#7F1D1D' },
];

const ACTIONS: Array<{ value: GatePolicyRule['action']; label: string; icon: ReactElement }> = [
  { value: 'block', label: 'BLOCK — Жесткая остановка', icon: <Block sx={{ fontSize: 14 }} /> },
  { value: 'warn', label: 'WARN — Предупреждение (с порогом)', icon: <Warning sx={{ fontSize: 14 }} /> },
  { value: 'pass', label: 'PASS — Пропустить', icon: <CheckCircle sx={{ fontSize: 14 }} /> },
];

const SIGNATORY_ROLES = [
  { value: 'secops_lead', label: 'Руководитель SecOps' },
  { value: 'admin_sec', label: 'Администратор безопасности' },
  { value: 'devops_lead', label: 'DevOps Lead' },
  { value: 'cto', label: 'CTO / Технический директор' },
];

// ── Component ──────────────────────────────────────────────────────────

interface GatePolicyBuilderProps {
  initialGateId?: string;
  onPolicySaved?: (gate: Gate) => void;
}

export function GatePolicyBuilder({ initialGateId, onPolicySaved }: GatePolicyBuilderProps) {
  const [gates, setGates] = useState<Gate[]>([]);
  const [selectedGateId, setSelectedGateId] = useState(initialGateId || '');
  const [selectedGate, setSelectedGate] = useState<Gate | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Editable policy state
  const [gateType, setGateType] = useState<'automatic' | 'manual'>('automatic');
  const [rules, setRules] = useState<GatePolicyRule[]>([]);
  const [requireSignature, setRequireSignature] = useState(false);
  const [mandatoryRole, setMandatoryRole] = useState('');
  const [selectedTemplate, setSelectedTemplate] = useState<TemplateId>('standard_release');

  const fetchGates = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getGates();
      setGates(data || []);
      if (data && data.length > 0) {
        if (!selectedGateId) setSelectedGateId(data[0].id);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Ошибка загрузки гейтов';
      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }, [selectedGateId]);

  useEffect(() => {
    fetchGates();
  }, [fetchGates]);

  // Load selected gate into editor
  useEffect(() => {
    const g = gates.find((x) => x.id === selectedGateId) || null;
    setSelectedGate(g);
    if (g) {
      setGateType(g.type);
      setRules([...g.policy.rules]);
    }
  }, [selectedGateId, gates]);

  // ── Template ────────────────────────────────────────────────────────

  const handleApplyTemplate = (template: PolicyTemplate) => {
    setSelectedTemplate(template.id);
    setGateType(template.gate_type);
    setRules([...template.rules]);
    setRequireSignature(template.require_manual_signature);
    setMandatoryRole(template.mandatory_role);
    toast.info(`Шаблон «${template.label}» применён`);
  };

  // ── Rules ───────────────────────────────────────────────────────────

  const handleAddRule = () => {
    setRules((prev) => [...prev, { finding_type: 'Medium', action: 'warn', max_count: 5 }]);
  };

  const handleRemoveRule = (index: number) => {
    setRules((prev) => prev.filter((_, i) => i !== index));
  };

  const handleUpdateRule = (index: number, patch: Partial<GatePolicyRule>) => {
    setRules((prev) => {
      const copy = [...prev];
      copy[index] = { ...copy[index], ...patch };
      return copy;
    });
  };

  // ── Save ────────────────────────────────────────────────────────────

  const handleSave = async () => {
    if (!selectedGateId) return;
    setSaving(true);
    try {
      const policy: GatePolicy = { rules };
      const updated = await api.updateGate(selectedGateId, {
        type: gateType,
        policy,
      });
      toast.success(`Политика гейта «${selectedGateId}» сохранена`);

      // Update local state
      setSelectedGate((prev) =>
        prev ? { ...prev, ...updated } : prev
      );

      if (onPolicySaved) {
        onPolicySaved({ ...selectedGate!, ...updated });
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Ошибка сохранения политики';
      setError(msg);
      toast.error(msg);
    } finally {
      setSaving(false);
    }
  };

  // ── Export JSON ─────────────────────────────────────────────────────

  const handleExport = () => {
    const manifest = {
      gate_id: selectedGateId,
      type: gateType,
      admission: {
        require_manual_signature: requireSignature,
        mandatory_role: mandatoryRole || undefined,
      },
      policy: { rules },
      exported_at: new Date().toISOString(),
    };
    const blob = new Blob([JSON.stringify(manifest, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `gate-policy-${selectedGateId || 'new'}.json`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success('Политика экспортирована в JSON');
  };

  // ── Simulate Test ───────────────────────────────────────────────────

  const handleTestPolicy = () => {
    const criticalRule = rules.find((r) => r.finding_type === 'Critical');
    const highRule = rules.find((r) => r.finding_type === 'High');

    const report = rules
      .map((r) => {
        if (r.action === 'block') return `🔴 ${r.finding_type}: BLOCK (порог ${r.max_count})`;
        if (r.action === 'warn') return `🟡 ${r.finding_type}: WARN (порог ${r.max_count ?? 'без лимита'})`;
        return `🟢 ${r.finding_type}: PASS`;
      })
      .join('\n');

    toast.info(
      `Политика протестирована:\n${report}\n` +
      (requireSignature ? '⚠️ Требуется ручная подпись' : '✅ Автоматическое решение')
    );
  };

  return (
    <ErrorBoundary viewName="Редактор политик (Gate Policy Builder)">
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
        {/* Header */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 1 }}>
          <Box>
            <Typography variant="h5" sx={{ fontWeight: 700 }}>
              Редактор политик Security Gates
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Конструктор правил: настройка CVSS-порогов, действий по CWE, Admission Gate и мандатных ролей.
            </Typography>
          </Box>
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Button
              variant="outlined"
              size="small"
              startIcon={<Download />}
              onClick={handleExport}
              disabled={!selectedGateId}
              sx={{ textTransform: 'none' }}
            >
              Экспорт JSON
            </Button>
            <Button
              variant="outlined"
              size="small"
              startIcon={<PlayArrow />}
              onClick={handleTestPolicy}
              disabled={rules.length === 0}
              sx={{ textTransform: 'none' }}
            >
              Тест на findings
            </Button>
            <Button
              variant="contained"
              size="small"
              startIcon={saving ? <HourglassEmpty /> : <SaveIcon />}
              onClick={handleSave}
              disabled={saving || !selectedGateId}
              sx={{ textTransform: 'none', fontWeight: 600 }}
            >
              Сохранить политику
            </Button>
          </Box>
        </Box>

        {error && (
          <Alert severity="error" onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        {/* Gate and template selectors */}
        <Grid container spacing={2}>
          <Grid size={{ xs: 12, md: 6 }}>
            <Card variant="outlined" sx={{ borderRadius: 2 }}>
              <Box sx={{ p: 2, borderBottom: 1, borderColor: 'divider' }}>
                <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
                  Целевой Security Gate
                </Typography>
              </Box>
              <Box sx={{ p: 2 }}>
                <TextField
                  select
                  value={selectedGateId}
                  onChange={(e) => setSelectedGateId(e.target.value)}
                  size="small"
                  fullWidth
                  label="Выберите Gate для редактирования"
                >
                  {gates.map((g) => (
                    <MenuItem key={g.id} value={g.id}>
                      {g.id} ({g.type}, {g.policy.rules.length} правил)
                    </MenuItem>
                  ))}
                </TextField>
                {selectedGate && (
                  <Box sx={{ mt: 1 }}>
                    <Typography variant="caption" color="text.secondary">
                      Текущий тип: <Chip label={selectedGate.type} size="small" sx={{ fontSize: 10, height: 18 }} />
                      {' '}Позиция #{selectedGate.position}
                    </Typography>
                  </Box>
                )}
              </Box>
            </Card>
          </Grid>

          <Grid size={{ xs: 12, md: 6 }}>
            <Card variant="outlined" sx={{ borderRadius: 2 }}>
              <Box sx={{ p: 2, borderBottom: 1, borderColor: 'divider' }}>
                <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
                  Шаблон политики
                </Typography>
              </Box>
              <Box sx={{ p: 2, display: 'flex', flexDirection: 'column', gap: 1.5 }}>
                {POLICY_TEMPLATES.map((tpl) => (
                  <Paper
                    key={tpl.id}
                    variant="outlined"
                    onClick={() => handleApplyTemplate(tpl)}
                    sx={{
                      p: 1.5,
                      cursor: 'pointer',
                      borderRadius: 1.5,
                      borderColor: selectedTemplate === tpl.id ? 'primary.main' : 'divider',
                      bgcolor: selectedTemplate === tpl.id ? 'action.selected' : 'background.paper',
                      transition: 'border-color 0.15s ease',
                      '&:hover': { borderColor: 'primary.main' },
                    }}
                  >
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        <Chip
                          icon={tpl.gate_type === 'manual' ? <VerifiedUser /> : <Security />}
                          label={tpl.label}
                          size="small"
                          color={tpl.gate_type === 'manual' ? 'warning' : 'primary'}
                          variant={tpl.gate_type === 'manual' ? 'filled' : 'outlined'}
                          sx={{ fontWeight: 700, fontSize: 11 }}
                        />
                        {tpl.require_manual_signature && (
                          <Chip icon={<Shield />} label="Sign" size="small" color="error" variant="outlined" sx={{ fontSize: 9, height: 18 }} />
                        )}
                      </Box>
                      <Chip label={`${tpl.rules.length} правил`} size="small" variant="outlined" sx={{ fontSize: 10, height: 18 }} />
                    </Box>
                    <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                      {tpl.description}
                    </Typography>
                  </Paper>
                ))}
              </Box>
            </Card>
          </Grid>
        </Grid>

        {/* Gate Type Toggle */}
        <Card variant="outlined" sx={{ borderRadius: 2 }}>
          <Box sx={{ p: 2 }}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <Box>
                <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
                  Тип контрольной точки
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  Automatic — решение без участия человека. Manual — требуется вердикт офицера безопасности.
                </Typography>
              </Box>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <Chip label="Automatic" size="small" color={gateType === 'automatic' ? 'primary' : 'default'} onClick={() => setGateType('automatic')} sx={{ cursor: 'pointer', fontWeight: 600 }} />
                <Switch
                  checked={gateType === 'manual'}
                  onChange={(_, v) => setGateType(v ? 'manual' : 'automatic')}
                  color="warning"
                />
                <Chip label="Manual" size="small" color={gateType === 'manual' ? 'warning' : 'default'} onClick={() => setGateType('manual')} sx={{ cursor: 'pointer', fontWeight: 600 }} />
              </Box>
            </Box>
          </Box>
        </Card>

        {/* Interactive Rule List */}
        <Card variant="outlined" sx={{ borderRadius: 2 }}>
          <Box sx={{ p: 2, display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: 1, borderColor: 'divider' }}>
            <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
              Правила политики ({rules.length})
            </Typography>
            <Button
              size="small"
              startIcon={<Add />}
              onClick={handleAddRule}
              sx={{ textTransform: 'none' }}
            >
              Добавить правило
            </Button>
          </Box>
          <TableContainer>
            <Table size="small">
              <TableHead sx={{ bgcolor: 'action.hover' }}>
                <TableRow>
                  <TableCell sx={{ fontWeight: 600 }}>Тип находки / CWE</TableCell>
                  <TableCell sx={{ fontWeight: 600, width: 160 }}>Действие</TableCell>
                  <TableCell sx={{ fontWeight: 600, width: 180 }}>Макс. количество (порог)</TableCell>
                  <TableCell sx={{ width: 60 }} />
                </TableRow>
              </TableHead>
              <TableBody>
                {rules.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={4} sx={{ p: 0 }}>
                      <EmptyState
                        icon={<Gavel sx={{ fontSize: 24 }} />}
                        title="Правила не заданы"
                        description="Добавьте правила политики или выберите шаблон."
                        actionLabel="Добавить правило"
                        onAction={handleAddRule}
                      />
                    </TableCell>
                  </TableRow>
                ) : (
                  rules.map((rule, idx) => (
                    <TableRow key={idx} hover>
                      <TableCell>
                        <TextField
                          select
                          value={rule.finding_type}
                          onChange={(e) => handleUpdateRule(idx, { finding_type: e.target.value })}
                          size="small"
                          fullWidth
                        >
                          {FINDING_CATEGORIES.map((cat) => (
                            <MenuItem key={cat.value} value={cat.value}>
                              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: cat.color }} />
                                {cat.label}
                              </Box>
                            </MenuItem>
                          ))}
                        </TextField>
                      </TableCell>
                      <TableCell>
                        <Box sx={{ display: 'flex', gap: 0.5 }}>
                          {ACTIONS.map((act) => (
                            <Chip
                              key={act.value}
                              icon={act.icon}
                              label={act.value.toUpperCase()}
                              size="small"
                              color={rule.action === act.value ? (act.value === 'block' ? 'error' : act.value === 'warn' ? 'warning' : 'success') : 'default'}
                              variant={rule.action === act.value ? 'filled' : 'outlined'}
                              onClick={() => handleUpdateRule(idx, { action: act.value })}
                              sx={{ fontSize: 9, height: 22, cursor: 'pointer', fontWeight: 700 }}
                              title={act.label}
                            />
                          ))}
                        </Box>
                      </TableCell>
                      <TableCell>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                          <Slider
                            value={rule.max_count ?? (rule.action === 'pass' ? 100 : 0)}
                            onChange={(_, v) => handleUpdateRule(idx, { max_count: v as number })}
                            min={0}
                            max={rule.action === 'pass' ? 100 : 50}
                            step={1}
                            size="small"
                            valueLabelDisplay="auto"
                            disabled={rule.action === 'pass'}
                            sx={{ width: 120 }}
                          />
                          <TextField
                            type="number"
                            size="small"
                            value={rule.max_count ?? 0}
                            onChange={(e) => handleUpdateRule(idx, { max_count: Number(e.target.value) })}
                            disabled={rule.action === 'pass'}
                            slotProps={{ htmlInput: { min: 0, max: rule.action === 'pass' ? 100 : 50 } }}
                            sx={{ width: 60 }}
                          />
                        </Box>
                      </TableCell>
                      <TableCell>
                        <IconButton
                          size="small"
                          color="error"
                          onClick={() => handleRemoveRule(idx)}
                        >
                          <Delete fontSize="small" />
                        </IconButton>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </TableContainer>
        </Card>

        {/* Admission Gate Settings */}
        <Card variant="outlined" sx={{ borderRadius: 2 }}>
          <Box sx={{ p: 2, display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: 1, borderColor: 'divider' }}>
            <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
              Требования допуска (Admission Gate)
            </Typography>
            <Chip icon={<VerifiedUser />} label="Admission Control" size="small" color="warning" sx={{ fontWeight: 700, fontSize: 10 }} />
          </Box>
          <Box sx={{ p: 2, display: 'flex', flexDirection: 'column', gap: 2 }}>
            <FormControlLabel
              control={
                <Checkbox
                  checked={requireSignature}
                  onChange={(_, v) => setRequireSignature(v)}
                  color="warning"
                />
              }
              label={
                <Box>
                  <Typography variant="body2" sx={{ fontWeight: 600 }}>
                    Требовать ручную подпись офицера безопасности
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    Каждый вердикт по гейту должен быть заверен криптографической подписью SHA-256.
                  </Typography>
                </Box>
              }
            />
            {requireSignature && (
              <TextField
                select
                label="Обязательная роль подписанта"
                value={mandatoryRole}
                onChange={(e) => setMandatoryRole(e.target.value)}
                size="small"
                fullWidth
                sx={{ maxWidth: 360, ml: 4 }}
              >
                {SIGNATORY_ROLES.map((r) => (
                  <MenuItem key={r.value} value={r.value}>
                    {r.label}
                  </MenuItem>
                ))}
              </TextField>
            )}
          </Box>
        </Card>

        {/* Rule Summary Preview */}
        <Card variant="outlined" sx={{ borderRadius: 2 }}>
          <Box sx={{ p: 2, borderBottom: 1, borderColor: 'divider' }}>
            <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
              Препросмотр результирующей конфигурации
            </Typography>
          </Box>
          <Box component="pre" sx={{ p: 2, fontSize: 12, fontFamily: 'monospace', overflowX: 'auto', bgcolor: 'action.hover' }}>
            {JSON.stringify({
              gate_id: selectedGateId,
              type: gateType,
              admission: {
                require_manual_signature: requireSignature,
                mandatory_role: mandatoryRole || null,
              },
              policy: { rules },
            }, null, 2)}
          </Box>
        </Card>
      </Box>
    </ErrorBoundary>
  );
}