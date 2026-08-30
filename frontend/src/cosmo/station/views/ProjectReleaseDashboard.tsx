/**
 * NX-FLASH-06: Project Release Dashboard — readiness summary + batch actions.
 */
import { useEffect, useState, useCallback } from 'react';
import {
  Box, Typography, Button, Select, MenuItem,
  Chip, Paper, Alert, CircularProgress,
} from '@mui/material';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { PlayArrow, Refresh } from '@mui/icons-material';
import { api, type Application, type ReleaseType, type Build } from '../api';
import { ErrorBoundary } from '../../shared/ErrorBoundary';
import { PageHeader } from '../minimal/PageHeader';
import { StatusChip } from '../minimal/StatusChip';
import { toast } from '../../shared/toast';

interface DashboardProps {
  projectId: string;
  onBack: () => void;
}

export function ProjectReleaseDashboard({ projectId, onBack }: DashboardProps) {
  const [apps, setApps] = useState<Application[]>([]);
  const [releaseTypes, setReleaseTypes] = useState<ReleaseType[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedTypes, setSelectedTypes] = useState<Record<string, string>>({});

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [appsData, typesData] = await Promise.all([
        api.getAllApps({ projectId }),
        api.getReleaseTypes(),
      ]);
      setApps(appsData || []);
      setReleaseTypes(typesData || []);
    } catch (err: unknown) {
      toast.error((err as Error)?.message || 'Ошибка загрузки');
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const readyCount = apps.filter((a) => a.status === 'active').length;

  const columns: GridColDef<Application>[] = [
    {
      field: 'id', headerName: 'Приложение', width: 180,
      renderCell: (p) => <span style={{ fontFamily: 'monospace', fontWeight: 600, fontSize: 12 }}>{p.row.id}</span>,
    },
    { field: 'level', headerName: 'Уровень', width: 80, renderCell: (p) => <Chip label={`L${p.row.level}`} size="small" sx={{ fontSize: 9, height: 18 }} /> },
    {
      field: 'status', headerName: 'Статус', width: 100,
      renderCell: (p) => <StatusChip status={p.row.status || 'active'} />,
    },
    {
      field: 'release_type', headerName: 'Release Type', width: 200,
      renderCell: (p) => (
        <Select size="small" value={selectedTypes[p.row.id] || ''}
          onChange={(e) => setSelectedTypes((prev) => ({ ...prev, [p.row.id]: e.target.value }))}
          displayEmpty sx={{ minWidth: 160, fontSize: 11 }}>
          <MenuItem value="">— Не выбрано —</MenuItem>
          {releaseTypes.map((rt) => <MenuItem key={rt.id} value={rt.id} sx={{ fontSize: 11 }}>{rt.name}</MenuItem>)}
        </Select>
      ),
    },
  ];

  return (
    <ErrorBoundary viewName="Release Dashboard">
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        <PageHeader
          title="Release Readiness Dashboard"
          subtitle={`${readyCount}/${apps.length} готовых · ${releaseTypes.length} типов релизов`}
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
          <Alert severity="info">Нет приложений в проекте</Alert>
        ) : (
          <>
            {/* Readiness summary */}
            <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
              <Box sx={{ display: 'flex', gap: 3, flexWrap: 'wrap' }}>
                <Box><Typography variant="h4" sx={{ fontWeight: 800 }}>{apps.length}</Typography><Typography variant="caption" color="text.secondary">Всего приложений</Typography></Box>
                <Box><Typography variant="h4" sx={{ fontWeight: 800, color: 'success.main' }}>{readyCount}</Typography><Typography variant="caption" color="text.secondary">Готовых к релизу</Typography></Box>
                <Box><Typography variant="h4" sx={{ fontWeight: 800, color: 'warning.main' }}>{apps.length - readyCount}</Typography><Typography variant="caption" color="text.secondary">Требуют внимания</Typography></Box>
              </Box>
            </Paper>

            {/* Data Grid */}
            <DataGrid
              columns={columns}
              rows={apps}
              getRowId={(row: any) => row.id}
              density="compact"
              disableRowSelectionOnClick
              disableColumnMenu
              sx={{
                height: 440, border: '1px solid', borderColor: 'divider', borderRadius: 2,
                '& .MuiDataGrid-columnHeaders': { bgcolor: 'action.hover', fontWeight: 600, fontSize: 12 },
                '& .MuiDataGrid-cell': { fontSize: 12 },
              }}
            />

            {/* Actions */}
            <Box sx={{ display: 'flex', gap: 1, justifyContent: 'flex-end' }}>
              <Button variant="contained" startIcon={<PlayArrow />}
                disabled={Object.values(selectedTypes).every((v) => !v)}
                onClick={() => toast.info('Перейдите в Batch Constructor для создания batch release')}
                sx={{ textTransform: 'none', fontWeight: 600 }}>
                Создать Batch Release
              </Button>
            </Box>
          </>
        )}
      </Box>
    </ErrorBoundary>
  );
}