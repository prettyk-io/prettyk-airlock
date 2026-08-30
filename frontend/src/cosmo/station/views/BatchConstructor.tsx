/**
 * NX-FLASH-06: Project Release Batch Constructor.
 */
import { useEffect, useState, useCallback } from 'react';
import {
  Box, Typography, Button, TextField, Select, MenuItem,
  Chip, Paper, Alert, CircularProgress, Divider,
} from '@mui/material';
import { PlayArrow, Refresh } from '@mui/icons-material';
import { api, type Application, type ReleaseType, type BatchRelease } from '../api';
import { ErrorBoundary } from '../../shared/ErrorBoundary';
import { PageHeader } from '../minimal/PageHeader';
import { StatusChip } from '../minimal/StatusChip';
import { toast } from '../../shared/toast';

interface BatchConstructorProps {
  projectId: string;
  onBack: () => void;
}

export function BatchConstructor({ projectId, onBack }: BatchConstructorProps) {
  const [apps, setApps] = useState<Application[]>([]);
  const [releaseTypes, setReleaseTypes] = useState<ReleaseType[]>([]);
  const [batchReleases, setBatchReleases] = useState<BatchRelease[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedTypes, setSelectedTypes] = useState<Record<string, string>>({});
  const [templateTypeId, setTemplateTypeId] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [appsData, typesData, batchesData] = await Promise.all([
        api.getAllApps({ projectId }),
        api.getReleaseTypes(),
        api.getBatchReleases(projectId),
      ]);
      setApps(appsData || []);
      setReleaseTypes(typesData || []);
      setBatchReleases(batchesData || []);
      // Pre-select first release type as template
      if (typesData && typesData.length > 0 && !templateTypeId) {
        setTemplateTypeId(typesData[0].id);
        const prefill: Record<string, string> = {};
        (appsData || []).forEach((a) => { prefill[a.id] = typesData[0].id; });
        setSelectedTypes(prefill);
      }
    } catch (err: unknown) {
      toast.error((err as Error)?.message || 'Ошибка загрузки');
    } finally {
      setLoading(false);
    }
  }, [projectId, templateTypeId]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleTemplateApply = () => {
    if (!templateTypeId) return;
    const prefill: Record<string, string> = {};
    apps.forEach((a) => { prefill[a.id] = templateTypeId; });
    setSelectedTypes(prefill);
  };

  const handleCreateBatch = async () => {
    const appList = apps.filter((a) => selectedTypes[a.id]);
    if (appList.length === 0) return;
    setSubmitting(true);
    try {
      await api.createBatchRelease(projectId, {
        apps: appList.map((a) => ({
          app_id: a.id,
          release_type_id: selectedTypes[a.id],
        })),
        template_release_type_id: templateTypeId || undefined,
      });
      toast.success('Batch release создан');
      await fetchData();
    } catch (err: unknown) {
      toast.error((err as Error)?.message || 'Ошибка создания batch release');
    } finally { setSubmitting(false); }
  };

  const handleRetryChild = async (batchId: string, appId: string) => {
    try {
      await api.retryChildRelease(batchId, appId);
      toast.success(`Retry запущен для ${appId}`);
      await fetchData();
    } catch (err: unknown) {
      toast.error((err as Error)?.message || 'Ошибка retry');
    }
  };

  const typeMap = new Map(releaseTypes.map((t) => [t.id, t]));

  return (
    <ErrorBoundary viewName="Batch Constructor">
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        <PageHeader
          title="Batch Release Constructor"
          subtitle={`${apps.length} приложений в проекте · ${releaseTypes.length} типов релизов`}
          action={
            <Box sx={{ display: 'flex', gap: 1 }}>
              <Button size="small" startIcon={<Refresh />} onClick={fetchData} disabled={loading} sx={{ textTransform: 'none' }}>Обновить</Button>
              <Button size="small" variant="outlined" onClick={onBack} sx={{ textTransform: 'none' }}>← Назад</Button>
            </Box>
          }
        />

        {loading ? (
          <CircularProgress sx={{ mx: 'auto' }} />
        ) : apps.length === 0 ? (
          <Alert severity="info">В проекте нет приложений для batch release</Alert>
        ) : (
          <>
            {/* Template selector */}
            <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
              <Box sx={{ display: 'flex', gap: 2, alignItems: 'center', flexWrap: 'wrap' }}>
                <Typography variant="body2" sx={{ fontWeight: 600 }}>Template Release Type:</Typography>
                <Select size="small" value={templateTypeId} onChange={(e) => setTemplateTypeId(e.target.value)} sx={{ minWidth: 200 }}>
                  {releaseTypes.map((rt) => <MenuItem key={rt.id} value={rt.id}>{rt.name}</MenuItem>)}
                </Select>
                <Button size="small" variant="outlined" onClick={handleTemplateApply} sx={{ textTransform: 'none' }}>Применить ко всем</Button>
              </Box>
            </Paper>

            {/* App list with per-app release type */}
            <Paper variant="outlined" sx={{ borderRadius: 2 }}>
              <Box sx={{ p: 2, borderBottom: 1, borderColor: 'divider' }}>
                <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>Приложения</Typography>
              </Box>
              <Box sx={{ maxHeight: 400, overflow: 'auto' }}>
                {apps.map((app) => (
                  <Box key={app.id} sx={{ p: 1.5, borderBottom: 1, borderColor: 'divider', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <Box>
                      <Typography variant="body2" sx={{ fontWeight: 600, fontFamily: 'monospace', fontSize: 13 }}>{app.id}</Typography>
                      <Box sx={{ display: 'flex', gap: 0.5, mt: 0.3 }}>
                        <Chip label={`L${app.level}`} size="small" sx={{ fontSize: 9, height: 16 }} />
                        {app.project_id && <Chip label={app.project_id} size="small" variant="outlined" sx={{ fontSize: 9, height: 16 }} />}
                      </Box>
                    </Box>
                    <Select size="small" value={selectedTypes[app.id] || ''}
                      onChange={(e) => setSelectedTypes((prev) => ({ ...prev, [app.id]: e.target.value }))}
                      sx={{ minWidth: 180 }}
                      displayEmpty>
                      <MenuItem value="">— Не выбрано —</MenuItem>
                      {releaseTypes.map((rt) => <MenuItem key={rt.id} value={rt.id}>{rt.name}</MenuItem>)}
                    </Select>
                  </Box>
                ))}
              </Box>
            </Paper>

            {/* Create button */}
            <Box sx={{ display: 'flex', gap: 1 }}>
              <Button variant="contained" startIcon={<PlayArrow />}
                onClick={handleCreateBatch}
                disabled={submitting || Object.values(selectedTypes).every((v) => !v)}
                sx={{ textTransform: 'none', fontWeight: 600 }}>
                {submitting ? 'Создание...' : 'Создать Batch Release'}
              </Button>
            </Box>
          </>
        )}

        {/* History */}
        {batchReleases.length > 0 && (
          <Paper variant="outlined" sx={{ borderRadius: 2 }}>
            <Box sx={{ p: 2, borderBottom: 1, borderColor: 'divider' }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>История Batch Releases ({batchReleases.length})</Typography>
            </Box>
            <Box sx={{ maxHeight: 300, overflow: 'auto' }}>
              {batchReleases.map((br) => (
                <Box key={br.id} sx={{ p: 2, borderBottom: 1, borderColor: 'divider' }}>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                    <Typography variant="body2" sx={{ fontWeight: 700, fontFamily: 'monospace' }}>{br.id}</Typography>
                    <StatusChip status={br.status} />
                  </Box>
                  {br.apps.map((a) => (
                    <Box key={a.app_id} sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', py: 0.5, pl: 2 }}>
                      <Typography variant="caption" sx={{ fontFamily: 'monospace' }}>{a.app_id}</Typography>
                      <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
                        <StatusChip status={a.status} />
                        {a.status === 'failed' && (
                          <Button size="small" color="warning" onClick={() => handleRetryChild(br.id, a.app_id)} sx={{ textTransform: 'none', fontSize: 10, minHeight: 24 }}>
                            Retry
                          </Button>
                        )}
                      </Box>
                    </Box>
                  ))}
                </Box>
              ))}
            </Box>
          </Paper>
        )}
      </Box>
    </ErrorBoundary>
  );
}