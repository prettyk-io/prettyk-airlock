/**
 * NX-FLASH-01/02: Project Detail — metadata, team, apps Data Grid.
 */
import { useEffect, useState, useCallback } from 'react';
import {
  Box, Typography, Button, Chip, Paper, Tabs, Tab,
  Alert, CircularProgress, Card, CardContent, Grid,
} from '@mui/material';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { ArrowBack, Refresh } from '@mui/icons-material';
import { api, type Project, type ProjectMember, type Application } from '../api';
import { ErrorBoundary } from '../../shared/ErrorBoundary';
import { PageHeader } from '../minimal/PageHeader';
import { StatusChip } from '../minimal/StatusChip';
import { EmptyTable } from '../minimal/EmptyTable';

interface ProjectDetailProps {
  projectId: string;
  onBack: () => void;
  onNavigate?: (view: string, params?: Record<string, string>) => void;
}

export function ProjectDetail({ projectId, onBack, onNavigate }: ProjectDetailProps) {
  const [project, setProject] = useState<Project | null>(null);
  const [apps, setApps] = useState<Application[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState(0);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [proj, appsData] = await Promise.all([
        api.getProject(projectId),
        api.getAllApps({ projectId }),
      ]);
      setProject(proj);
      setApps(appsData || []);
    } catch (err: unknown) {
      setError((err as Error)?.message || 'Ошибка загрузки проекта');
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const appColumns: GridColDef<Application>[] = [
    { field: 'id', headerName: 'ID', width: 160, renderCell: (p) => <span style={{ fontFamily: 'monospace', fontWeight: 600 }}>{p.row.id}</span> },
    { field: 'level', headerName: 'Уровень', width: 90, renderCell: (p) => <Chip label={`L${p.row.level}`} size="small" sx={{ fontSize: 9, height: 18 }} /> },
    { field: 'domain_id', headerName: 'KITS', width: 120, renderCell: (p) => <Chip label={p.row.domain_id} size="small" variant="outlined" sx={{ fontSize: 9, height: 18 }} /> },
    {
      field: 'repo_binding', headerName: 'Git', width: 180,
      renderCell: (p) => <span style={{ fontSize: 11, fontFamily: 'monospace' }}>{p.row.repo_binding?.repo_path || '—'}</span>,
    },
    {
      field: 'status', headerName: 'Статус', width: 110,
      renderCell: (p) => <StatusChip status={p.row.status || 'active'} />,
    },
  ];

  const team = project?.team || [];
  const inheritedMembers = team.filter((m: ProjectMember) => m.inherited);
  const localMembers = team.filter((m: ProjectMember) => !m.inherited);

  return (
    <ErrorBoundary viewName="Project Detail">
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        {/* Header */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <Button size="small" onClick={onBack} startIcon={<ArrowBack />} sx={{ textTransform: 'none' }}>Назад</Button>
            {project ? (
              <Box>
                <Typography variant="h5" sx={{ fontWeight: 700 }}>{project.name}</Typography>
                <Typography variant="body2" color="text.secondary">{project.description || ''}</Typography>
              </Box>
            ) : (
              <CircularProgress size={20} />
            )}
          </Box>
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Button size="small" startIcon={<Refresh />} onClick={fetchData} disabled={loading} sx={{ textTransform: 'none' }}>Обновить</Button>
          </Box>
        </Box>

        {error && <Alert severity="error">{error}</Alert>}

        {loading && !project ? (
          <CircularProgress sx={{ mx: 'auto', mt: 4 }} />
        ) : project && (
          <>
            {/* Meta chips */}
            <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
              {(project.kits_tags || []).map((t: string) => <Chip key={t} label={t} size="small" variant="outlined" />)}
              <StatusChip status={project.status} />
              <Chip label={`Release: ${project.last_release || '—'}`} size="small" variant="outlined" />
              <Chip label={`Created by: ${project.created_by || '—'}`} size="small" variant="outlined" />
            </Box>

            {/* Tabs */}
            <Box sx={{ borderBottom: 1, borderColor: 'divider' }}>
              <Tabs value={tab} onChange={(_, v) => setTab(v)}>
                <Tab label={`Состав (${apps.length})`} sx={{ textTransform: 'none', fontWeight: 600 }} />
                <Tab label={`Команда (${team.length})`} sx={{ textTransform: 'none', fontWeight: 600 }} />
              </Tabs>
            </Box>

            {/* Tab 0: Apps Data Grid */}
            {tab === 0 && (
              apps.length === 0 ? (
                <EmptyTable title="Приложений нет" description="Добавьте приложения в проект." />
              ) : (
                <DataGrid
                  columns={appColumns}
                  rows={apps}
                  getRowId={(row: any) => row.id}
                  density="compact"
                  disableRowSelectionOnClick
                  disableColumnMenu
                  onRowClick={(params: any) => onNavigate?.('app-detail', { projectId, appId: params.row.id })}
                  sx={{
                    height: 400, border: '1px solid', borderColor: 'divider', borderRadius: 2,
                    '& .MuiDataGrid-columnHeaders': { bgcolor: 'action.hover', fontWeight: 600, fontSize: 12 },
                    '& .MuiDataGrid-row': { cursor: 'pointer' },
                    '& .MuiDataGrid-cell': { fontSize: 12 },
                  }}
                />
              )
            )}

            {/* Tab 1: Team */}
            {tab === 1 && (
              <Grid container spacing={2}>
                {localMembers.length > 0 && (
                  <Grid size={{ xs: 12, md: 6 }}>
                    <Card variant="outlined" sx={{ borderRadius: 2 }}>
                      <Box sx={{ p: 2, borderBottom: 1, borderColor: 'divider' }}>
                        <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>Локальные участники</Typography>
                      </Box>
                      <Box sx={{ p: 2 }}>
                        {localMembers.map((m: ProjectMember) => (
                          <Box key={m.id} sx={{ py: 0.5, display: 'flex', justifyContent: 'space-between' }}>
                            <Typography variant="body2" sx={{ fontWeight: 600 }}>{m.name}</Typography>
                            <Chip label={m.role} size="small" variant="outlined" sx={{ fontSize: 9, height: 18 }} />
                          </Box>
                        ))}
                      </Box>
                    </Card>
                  </Grid>
                )}
                {inheritedMembers.length > 0 && (
                  <Grid size={{ xs: 12, md: 6 }}>
                    <Card variant="outlined" sx={{ borderRadius: 2 }}>
                      <Box sx={{ p: 2, borderBottom: 1, borderColor: 'divider' }}>
                        <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>Унаследованные</Typography>
                      </Box>
                      <Box sx={{ p: 2 }}>
                        {inheritedMembers.map((m: ProjectMember) => (
                          <Box key={m.id} sx={{ py: 0.5, display: 'flex', justifyContent: 'space-between' }}>
                            <Typography variant="body2" sx={{ fontWeight: 600, color: 'text.secondary' }}>{m.name}</Typography>
                            <Chip label={`${m.role} ↳`} size="small" variant="outlined" sx={{ fontSize: 9, height: 18, color: 'text.disabled' }} />
                          </Box>
                        ))}
                      </Box>
                    </Card>
                  </Grid>
                )}
                {team.length === 0 && <Typography variant="body2" color="text.secondary" sx={{ p: 2 }}>Команда не назначена</Typography>}
              </Grid>
            )}
          </>
        )}
      </Box>
    </ErrorBoundary>
  );
}