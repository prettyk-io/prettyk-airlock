/**
 * FR-003: Projects Overview — main table shows projects, KITS switcher.
 *
 * Shows all available KITS domains as filter chips,
 * project count, L0/L1/L2 counters, status, last release, last modified.
 * Click row → project detail.
 */
import { useEffect, useState, useCallback } from 'react';
import {
  Box, Chip, ToggleButtonGroup, ToggleButton, Skeleton,
  Alert, Button,
} from '@mui/material';
import { Add, Refresh } from '@mui/icons-material';
import { DataGrid, type GridColDef, type GridRowParams } from '@mui/x-data-grid';
import { api, type Project, type KitsTag } from '../api';
import { ErrorBoundary } from '../../shared/ErrorBoundary';
import { PageHeader } from '../minimal/PageHeader';
import { StatusChip } from '../minimal/StatusChip';
import { EmptyTable } from '../minimal/EmptyTable';

interface ProjectsOverviewProps {
  onNavigate?: (view: string, params?: Record<string, string>) => void;
}

export function ProjectsOverview({ onNavigate }: ProjectsOverviewProps) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [kitsTags, setKitsTags] = useState<KitsTag[]>([]);
  const [activeKits, setActiveKits] = useState('all');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [projData, kitsData] = await Promise.all([
        api.getProjects(activeKits),
        api.getKitsTags(),
      ]);
      setProjects(projData || []);
      setKitsTags(kitsData || []);
    } catch (err: unknown) {
      setError((err as Error)?.message || 'Ошибка загрузки проектов');
    } finally {
      setLoading(false);
    }
  }, [activeKits]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const columns: GridColDef<Project>[] = [
    {
      field: 'name', headerName: 'Проект', width: 220, sortable: true,
      renderCell: (p) => (
        <Box sx={{ fontWeight: 700, fontFamily: 'monospace', fontSize: 13 }}>
          {p.row.name}
        </Box>
      ),
    },
    {
      field: 'kits_tags', headerName: 'КИТС', width: 180, sortable: false,
      renderCell: (p) => (
        <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
          {(p.row.kits_tags || []).map((t: string) => (
            <Chip key={t} label={t} size="small" variant="outlined" sx={{ fontSize: 9, height: 18 }} />
          ))}
        </Box>
      ),
    },
    {
      field: 'app_count', headerName: 'Приложений', width: 110, sortable: true,
      renderCell: (p) => (
        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
          <span style={{ fontWeight: 700 }}>{p.row.app_count}</span>
          <span style={{ fontSize: 10, color: '#94A3B8' }}>
            L0:{p.row.l0_count} L1:{p.row.l1_count} L2:{p.row.l2_count}
          </span>
        </Box>
      ),
    },
    {
      field: 'status', headerName: 'Статус', width: 120,
      renderCell: (p) => <StatusChip status={p.row.status} />,
    },
    {
      field: 'last_release', headerName: 'Посл. релиз', width: 160,
      renderCell: (p) => (
        <Box>
          <div style={{ fontWeight: 600, fontSize: 12 }}>{p.row.last_release || '—'}</div>
          {p.row.last_release_date && (
            <div style={{ fontSize: 10, color: '#94A3B8' }}>
              {new Date(p.row.last_release_date).toLocaleDateString('ru-RU')}
            </div>
          )}
        </Box>
      ),
    },
    {
      field: 'updated_at', headerName: 'Изменён', width: 130,
      renderCell: (p) => (
        <span style={{ fontSize: 11, color: '#64748B' }}>
          {new Date(p.row.updated_at).toLocaleDateString('ru-RU')}
        </span>
      ),
    },
  ];

  return (
    <ErrorBoundary viewName="Projects Overview">
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        <PageHeader
          title="Проекты"
          subtitle={`Всего проектов: ${projects.length}${activeKits !== 'all' ? ` · КИТС: ${activeKits}` : ''}`}
          action={
            <Box sx={{ display: 'flex', gap: 1 }}>
              <Button size="small" onClick={fetchData} disabled={loading} startIcon={<Refresh />} sx={{ textTransform: 'none' }}>
                Обновить
              </Button>
            </Box>
          }
        />

        {error && <Alert severity="error" onClose={() => setError(null)}>{error}</Alert>}

        {/* KITS Switcher */}
        {kitsTags.length > 0 && (
          <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
            <Chip
              label="Все КИТС"
              size="small"
              variant={activeKits === 'all' ? 'filled' : 'outlined'}
              color={activeKits === 'all' ? 'primary' : 'default'}
              onClick={() => setActiveKits('all')}
              sx={{ cursor: 'pointer', fontWeight: activeKits === 'all' ? 700 : 400 }}
            />
            {kitsTags.map((kt) => (
              <Chip
                key={kt.id}
                label={kt.label}
                size="small"
                variant={activeKits === kt.id ? 'filled' : 'outlined'}
                color={activeKits === kt.id ? 'primary' : 'default'}
                onClick={() => setActiveKits(kt.id)}
                sx={{ cursor: 'pointer', fontWeight: activeKits === kt.id ? 700 : 400 }}
              />
            ))}
          </Box>
        )}

        {/* Skeleton while loading */}
        {loading ? (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            {[1, 2, 3, 4, 5].map((i) => <Skeleton key={i} variant="rectangular" height={40} sx={{ borderRadius: 1 }} />)}
          </Box>
        ) : projects.length === 0 ? (
          <EmptyTable
            title="Проекты не найдены"
            description={activeKits === 'all' ? 'Создайте первый проект для начала работы.' : 'Нет проектов с выбранным тегом КИТС.'}
            actionLabel="Создать проект"
            onAction={() => onNavigate?.('projects-registry')}
          />
        ) : (
          <DataGrid
            columns={columns}
            rows={projects}
            getRowId={(row) => row.id}
            density="compact"
            disableRowSelectionOnClick
            disableColumnMenu
            onRowClick={(params: GridRowParams<Project>) => {
              onNavigate?.('project-detail', { projectId: params.row.id });
            }}
            sx={{
              height: 560,
              border: '1px solid', borderColor: 'divider', borderRadius: 2,
              '& .MuiDataGrid-columnHeaders': { bgcolor: 'action.hover', fontWeight: 600, fontSize: 12 },
              '& .MuiDataGrid-row': { cursor: 'pointer' },
              '& .MuiDataGrid-cell': { fontSize: 12, borderColor: 'divider' },
            }}
            slots={{
              noRowsOverlay: () => <EmptyTable title="Нет данных" description="Проекты не найдены." />,
            }}
          />
        )}
      </Box>
    </ErrorBoundary>
  );
}