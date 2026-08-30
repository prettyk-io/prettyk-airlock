/**
 * NX-FLASH-04: Flat Applications Registry — all apps, newest first, filterable.
 */
import { useEffect, useState, useMemo } from 'react';
import {
  Box, Typography, Chip, Alert, CircularProgress,
} from '@mui/material';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { api, type Application } from '../api';
import { ErrorBoundary } from '../../shared/ErrorBoundary';
import { PageHeader } from '../minimal/PageHeader';
import { StatusChip } from '../minimal/StatusChip';

interface FlatAppsRegistryProps {
  onNavigate?: (view: string, params?: Record<string, string>) => void;
}

export function FlatAppsRegistry({ onNavigate }: FlatAppsRegistryProps) {
  const [apps, setApps] = useState<Application[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterProject, setFilterProject] = useState('all');
  const [filterLevel, setFilterLevel] = useState<number | 'all'>('all');
  const [filterStatus, setFilterStatus] = useState('all');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api.getAllApps({})
      .then((data) => {
        if (cancelled) return;
        const sorted = [...(data || [])].sort((a, b) => {
          return (b.id > a.id ? 1 : -1); // newest first by id (as created_at proxy)
        });
        setApps(sorted);
      })
      .catch((err: Error) => { if (!cancelled) setError(err.message || 'Ошибка загрузки'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const projects = [...new Set(apps.map((a) => a.project_id || a.domain_id).filter((x): x is string => !!x))].sort();
  const levels = [...new Set(apps.map((a) => a.level))].sort();
  const statuses = [...new Set(apps.map((a) => a.status || 'active'))].sort();

  const filtered = useMemo(() => {
    return apps.filter((a) => {
      if (filterProject !== 'all' && (a.project_id || a.domain_id) !== filterProject) return false;
      if (filterLevel !== 'all' && a.level !== filterLevel) return false;
      if (filterStatus !== 'all' && (a.status || 'active') !== filterStatus) return false;
      return true;
    });
  }, [apps, filterProject, filterLevel, filterStatus]);

  const columns: GridColDef<Application>[] = [
    {
      field: 'id', headerName: 'Приложение', width: 180,
      renderCell: (p) => <span style={{ fontFamily: 'monospace', fontWeight: 600, fontSize: 12 }}>{p.row.id}</span>,
    },
    {
      field: 'project', headerName: 'Проект', width: 150,
      renderCell: (p) => (
        <Chip
          label={p.row.project_id || p.row.domain_id || '—'}
          size="small" variant="outlined"
          sx={{ fontSize: 9, height: 18, cursor: 'pointer' }}
          onClick={(e) => { e.stopPropagation(); if (p.row.project_id) onNavigate?.('project-detail', { projectId: p.row.project_id || '' }); }}
        />
      ),
    },
    {
      field: 'domain_id', headerName: 'KITS', width: 120,
      renderCell: (p) => <Chip label={p.row.domain_id} size="small" variant="outlined" sx={{ fontSize: 9, height: 18 }} />,
    },
    {
      field: 'level', headerName: 'Уровень', width: 80,
      renderCell: (p) => <Chip label={`L${p.row.level}`} size="small" sx={{ fontSize: 9, height: 18 }} />,
    },
    {
      field: 'status', headerName: 'Статус', width: 110,
      renderCell: (p) => <StatusChip status={p.row.status || 'active'} />,
    },
    {
      field: 'repo_binding', headerName: 'Git', width: 170,
      renderCell: (p) => <span style={{ fontSize: 11, fontFamily: 'monospace' }}>{p.row.repo_binding?.repo_path || '—'}</span>,
    },
  ];

  if (error) {
    return (
      <Box sx={{ p: 4, textAlign: 'center' }}>
        <Alert severity="error">{error}</Alert>
      </Box>
    );
  }

  return (
    <ErrorBoundary viewName="Flat Apps Registry">
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        <PageHeader title="Реестр приложений" subtitle={`${filtered.length} из ${apps.length}`} />

        {/* Filter chips */}
        <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
          <Chip label="Все проекты" size="small" variant={filterProject === 'all' ? 'filled' : 'outlined'}
            color={filterProject === 'all' ? 'primary' : 'default'}
            onClick={() => setFilterProject('all')} sx={{ cursor: 'pointer' }} />
          {projects.map((p) => (
            <Chip key={p} label={p} size="small" variant={filterProject === p ? 'filled' : 'outlined'}
              color={filterProject === p ? 'primary' : 'default'}
              onClick={() => setFilterProject(p)} sx={{ cursor: 'pointer' }} />
          ))}
        </Box>

        <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
          <Chip label="Все уровни" size="small" variant={filterLevel === 'all' ? 'filled' : 'outlined'}
            color={filterLevel === 'all' ? 'primary' : 'default'}
            onClick={() => setFilterLevel('all')} sx={{ cursor: 'pointer' }} />
          {levels.map((l) => (
            <Chip key={l} label={`L${l}`} size="small" variant={filterLevel === l ? 'filled' : 'outlined'}
              color={filterLevel === l ? 'primary' : 'default'}
              onClick={() => setFilterLevel(l)} sx={{ cursor: 'pointer' }} />
          ))}
        </Box>

        {loading ? (
          <CircularProgress sx={{ mx: 'auto', mt: 4 }} />
        ) : filtered.length === 0 ? (
          <Box sx={{ py: 6, textAlign: 'center', color: 'text.secondary' }}>
            <Typography>Приложения не найдены</Typography>
          </Box>
        ) : (
          <DataGrid
            columns={columns}
            rows={filtered}
            getRowId={(row: any) => row.id}
            density="compact"
            disableRowSelectionOnClick
            disableColumnMenu
            onRowClick={(params: any) => onNavigate?.('app-detail', { projectId: params.row.project_id || params.row.domain_id, appId: params.row.id })}
            sx={{
              height: 520, border: '1px solid', borderColor: 'divider', borderRadius: 2,
              '& .MuiDataGrid-columnHeaders': { bgcolor: 'action.hover', fontWeight: 600, fontSize: 12 },
              '& .MuiDataGrid-row': { cursor: 'pointer' },
              '& .MuiDataGrid-cell': { fontSize: 12 },
            }}
          />
        )}
      </Box>
    </ErrorBoundary>
  );
}