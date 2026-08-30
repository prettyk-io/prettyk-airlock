/**
 * NX-FLASH-05: Release Type Builder.
 */
import { useEffect, useState, useCallback } from 'react';
import {
  Box, Typography, Button, TextField, Switch, FormControlLabel,
  Chip, Paper, Select, MenuItem, Alert, CircularProgress,
  Tabs, Tab,
} from '@mui/material';
import { Add } from '@mui/icons-material';
import { api, type ReleaseType, type ReleaseStep } from '../api';
import { ErrorBoundary } from '../../shared/ErrorBoundary';
import { PageHeader } from '../minimal/PageHeader';
import { FormDialog } from '../minimal/FormDialog';
import { toast } from '../../shared/toast';

const APP_KINDS_LIST = ['microservice', 'gateway', 'frontend', 'mobile', 'library', 'database', 'broker'];
const FAILURE_POLICIES = ['continue', 'terminate'] as const;

export function ReleaseTypeBuilder() {
  const [types, setTypes] = useState<ReleaseType[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [tab, setTab] = useState(0);

  // Form state
  const [openCreate, setOpenCreate] = useState(false);
  const [name, setName] = useState('');
  const [appKinds, setAppKinds] = useState<string[]>([]);
  const [levels, setLevels] = useState<number[]>([1]);
  const [artifactKind, setArtifactKind] = useState('docker');
  const [steps, setSteps] = useState<ReleaseStep[]>([]);
  const [gates, setGates] = useState<string[]>([]);
  const [prettykCheck, setPrettykCheck] = useState(false);

  const fetchTypes = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.getReleaseTypes();
      setTypes(data || []);
    } catch (err: unknown) {
      toast.error((err as Error)?.message || 'Ошибка загрузки типов релизов');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchTypes(); }, [fetchTypes]);

  const selected = types.find((t) => t.id === selectedId);

  const handleSelect = (id: string) => {
    setSelectedId(id);
    const t = types.find((x) => x.id === id);
    if (t) {
      setName(t.name);
      setAppKinds(t.applicable_app_kinds || []);
      setLevels(t.levels || [1]);
      setArtifactKind(t.artifact_kind || 'docker');
      setSteps(t.steps || []);
      setGates(t.gates || []);
      setPrettykCheck(t.prettyk_check_enabled || false);
    }
  };

  const handleCreate = async () => {
    if (!name.trim()) return;
    setSaving(true);
    try {
      await api.createReleaseType({
        name: name.trim(), applicable_app_kinds: appKinds, levels,
        artifact_kind: artifactKind, steps, gates,
        prettyk_check_enabled: prettykCheck, package_rules: {},
      });
      toast.success('Тип релиза создан');
      setOpenCreate(false); setName(''); setSteps([]); setGates([]);
      await fetchTypes();
    } catch (err: unknown) {
      toast.error((err as Error)?.message || 'Ошибка создания');
    } finally { setSaving(false); }
  };

  const handleSave = async () => {
    if (!selectedId || !name.trim()) return;
    setSaving(true);
    try {
      await api.updateReleaseType(selectedId, {
        name: name.trim(), applicable_app_kinds: appKinds, levels,
        artifact_kind: artifactKind, steps, gates,
        prettyk_check_enabled: prettykCheck,
      });
      toast.success('Тип релиза сохранён');
      await fetchTypes();
    } catch (err: unknown) {
      toast.error((err as Error)?.message || 'Ошибка сохранения');
    } finally { setSaving(false); }
  };

  const handleDelete = async () => {
    if (!selectedId) return;
    try {
      await api.deleteReleaseType(selectedId);
      toast.success('Тип релиза удалён');
      setSelectedId(null); setName(''); setSteps([]);
      await fetchTypes();
    } catch (err: unknown) {
      toast.error((err as Error)?.message || 'Ошибка удаления');
    }
  };

  const addStep = () => {
    setSteps((prev) => [...prev, {
      id: `step-${Date.now()}`, name: '', order: prev.length + 1,
      required: true, enabled: true, failure_policy: 'terminate',
    }]);
  };

  const updateStep = (idx: number, patch: Partial<ReleaseStep>) => {
    setSteps((prev) => prev.map((s, i) => i === idx ? { ...s, ...patch } : s));
  };

  const deleteStep = (idx: number) => {
    setSteps((prev) => prev.filter((_, i) => i !== idx));
  };

  return (
    <ErrorBoundary viewName="Release Type Builder">
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        <PageHeader
          title="Release Type Builder"
          subtitle={`${types.length} типов релизов`}
          action={<Button variant="contained" size="small" startIcon={<Add />} onClick={() => { setSelectedId(null); setName(''); setSteps([]); setOpenCreate(true); }} sx={{ textTransform: 'none', fontWeight: 600 }}>Создать тип</Button>}
        />

        <Box sx={{ display: 'flex', gap: 2, height: 'calc(100vh - 200px)' }}>
          {/* Left: Type list */}
          <Paper variant="outlined" sx={{ width: 280, borderRadius: 2, p: 1, overflow: 'auto', flexShrink: 0 }}>
            <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1, px: 1 }}>Типы релизов</Typography>
            {loading ? <CircularProgress size={20} sx={{ mx: 'auto', display: 'block' }} /> : types.length === 0 ? (
              <Typography variant="body2" color="text.secondary" sx={{ p: 1 }}>Нет типов</Typography>
            ) : types.map((t) => (
              <Paper key={t.id} variant="outlined"
                onClick={() => handleSelect(t.id)}
                sx={{ p: 1, mb: 0.5, cursor: 'pointer', borderRadius: 1.5, borderColor: selectedId === t.id ? 'primary.main' : 'divider', bgcolor: selectedId === t.id ? 'action.selected' : 'background.paper', borderWidth: selectedId === t.id ? 2 : 1 }}>
                <Typography variant="caption" sx={{ fontWeight: 700, display: 'block' }}>{t.name}</Typography>
                <Typography variant="caption" color="text.secondary">{t.steps.length} steps · {t.levels.join(',')}</Typography>
              </Paper>
            ))}
          </Paper>

          {/* Right: Edit form */}
          <Paper variant="outlined" sx={{ flex: 1, borderRadius: 2, p: 2, overflow: 'auto' }}>
            {!selectedId && !openCreate ? (
              <Box sx={{ py: 6, textAlign: 'center', color: 'text.secondary' }}>
                <Typography>Выберите тип релиза слева или создайте новый</Typography>
              </Box>
            ) : (
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                <TextField label="Название" value={name} onChange={(e) => setName(e.target.value)} size="small" fullWidth />

                <Box>
                  <Typography variant="caption" sx={{ fontWeight: 600, display: 'block', mb: 0.5 }}>Типы приложений</Typography>
                  <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                    {APP_KINDS_LIST.map((k) => (
                      <Chip key={k} label={k} size="small"
                        variant={appKinds.includes(k) ? 'filled' : 'outlined'}
                        color={appKinds.includes(k) ? 'primary' : 'default'}
                        onClick={() => setAppKinds((prev) => prev.includes(k) ? prev.filter((x) => x !== k) : [...prev, k])}
                        sx={{ cursor: 'pointer' }} />
                    ))}
                  </Box>
                </Box>

                <Box>
                  <Typography variant="caption" sx={{ fontWeight: 600 }}>Уровни</Typography>
                  <Box sx={{ display: 'flex', gap: 1, mt: 0.5 }}>
                    {[0, 1, 2].map((l) => (
                      <Chip key={l} label={`L${l}`} size="small"
                        variant={levels.includes(l) ? 'filled' : 'outlined'}
                        color={levels.includes(l) ? 'primary' : 'default'}
                        onClick={() => setLevels((prev) => prev.includes(l) ? prev.filter((x) => x !== l) : [...prev, l])}
                        sx={{ cursor: 'pointer' }} />
                    ))}
                  </Box>
                </Box>

                <TextField label="Тип артефакта" value={artifactKind} onChange={(e) => setArtifactKind(e.target.value)} size="small" sx={{ maxWidth: 200 }} />

                {/* Steps */}
                <Box>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                    <Typography variant="caption" sx={{ fontWeight: 600 }}>Шаги ({steps.length})</Typography>
                    <Button size="small" onClick={addStep} sx={{ textTransform: 'none', fontSize: 11 }}>+ Добавить</Button>
                  </Box>
                  {steps.map((s, i) => (
                    <Paper key={i} variant="outlined" sx={{ p: 1, mb: 0.5, display: 'flex', gap: 1, alignItems: 'center', borderRadius: 1 }}>
                      <Typography variant="caption" sx={{ fontWeight: 700, minWidth: 24 }}>#{i + 1}</Typography>
                      <TextField size="small" value={s.name} onChange={(e) => updateStep(i, { name: e.target.value })} placeholder="Название" sx={{ flex: 1 }} />
                      <Select size="small" value={s.failure_policy} onChange={(e) => updateStep(i, { failure_policy: e.target.value as any })} sx={{ minWidth: 120 }}>
                        {FAILURE_POLICIES.map((p) => <MenuItem key={p} value={p}>{p === 'continue' ? '▶ Continue' : '⏹ Terminate'}</MenuItem>)}
                      </Select>
                      <FormControlLabel control={<Switch checked={s.required} onChange={(_, v) => updateStep(i, { required: v })} size="small" />} label="" />
                      <Button size="small" color="error" onClick={() => deleteStep(i)} sx={{ minWidth: 30, p: 0.5 }}>×</Button>
                    </Paper>
                  ))}
                </Box>

                {/* Gates */}
                <Box>
                  <Typography variant="caption" sx={{ fontWeight: 600, mb: 0.5, display: 'block' }}>Gates</Typography>
                  <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                    {gates.map((g, i) => (
                      <Chip key={i} label={g} size="small" onDelete={() => setGates((prev) => prev.filter((_, j) => j !== i))} />
                    ))}
                  </Box>
                  <TextField size="small" placeholder="Добавить gate..." sx={{ mt: 0.5, maxWidth: 200 }}
                    onKeyDown={(e: any) => { if (e.key === 'Enter' && e.target.value) { setGates((prev) => [...prev, e.target.value]); e.target.value = ''; } }} />
                </Box>

                <FormControlLabel control={<Switch checked={prettykCheck} onChange={(_, v) => setPrettykCheck(v)} />} label="PrettyK external check" />

                <Box sx={{ display: 'flex', gap: 1 }}>
                  <Button variant="contained" onClick={openCreate ? handleCreate : handleSave} disabled={saving || !name.trim()} sx={{ textTransform: 'none', fontWeight: 600 }}>
                    {openCreate ? 'Создать' : 'Сохранить'}
                  </Button>
                  {selectedId && <Button color="error" onClick={handleDelete} sx={{ textTransform: 'none' }}>Удалить</Button>}
                </Box>
              </Box>
            )}
          </Paper>
        </Box>
      </Box>
    </ErrorBoundary>
  );
}