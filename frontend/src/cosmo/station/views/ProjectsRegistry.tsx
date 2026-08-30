/**
 * FR-004: Projects Registry — list + creation.
 *
 * Flat project list, IT-Leader creates empty project with metadata,
 * then creates apps within it or adds existing ones.
 */
import { useEffect, useState, useCallback } from 'react';
import {
  Box, Typography, Button, TextField, Chip, Alert, Skeleton,
} from '@mui/material';
import { Add, Refresh } from '@mui/icons-material';
import { DataGrid, type GridColDef, type GridRowParams } from '@mui/x-data-grid';
import { api, type Project, type KitsTag } from '../api';
import { ErrorBoundary } from '../../shared/ErrorBoundary';
import { PageHeader } from '../minimal/PageHeader';
import { FormDialog } from '../minimal/FormDialog';
import { StatusChip } from '../minimal/StatusChip';
import { EmptyTable } from '../minimal/EmptyTable';
import { ProjectCreateWizard } from './ProjectCreateWizard';

interface ProjectsRegistryProps {
  onNavigate?: (view: string, params?: Record<string, string>) => void;
}

export function ProjectsRegistry({ onNavigate }: ProjectsRegistryProps) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [kitsTags, setKitsTags] = useState<KitsTag[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Create project form
  const [wizardOpen, setWizardOpen] = useState(false);
  const [simpleCreateOpen, setSimpleCreateOpen] = useState(false);
  const [newName, setNewName] = useState('');
  const [newDescription, setNewDescription] = useState('');
  const [newKitsTags, setNewKitsTags] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);

  const fetchProjects = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [projData, kitsData] = await Promise.all([
        api.getProjects(),
        api.getKitsTags(),
      ]);
      setProjects(projData || []);
      setKitsTags(kitsData || []);
    } catch (err: unknown) {
      setError((err as Error)?.message || 'Ошибка загрузки');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchProjects(); }, [fetchProjects]);

  const handleCreateProject = async () => {
    if (!newName.trim()) return;
    setSubmitting(true);
    try {
      await api.createProject({
        name: newName.trim(),
        description: newDescription.trim() || undefined,
        kits_tags: newKitsTags,
      });
      setSimpleCreateOpen(false);
      setNewName('');
      setNewDescription('');
      setNewKitsTags([]);
      await fetchProjects();
    } catch (err: unknown) {
      setError((err as Error)?.message || 'Ошибка создания проекта');
    } finally {
      setSubmitting(false);
    }
  };

  const columns: GridColDef<Project>[] = [
    {
      field: 'name', headerName: 'Проект', width: 220,
      renderCell: (p) => (
        <span style={{ fontWeight: 700, fontFamily: 'monospace', fontSize: 13 }}>{p.row.name}</span>
      ),
    },
    {
      field: 'kits_tags', headerName: 'КИТС', width: 200,
      renderCell: (p) => (
        <Box sx={{ display: 'flex', gap: 0.3, flexWrap: 'wrap' }}>
          {(p.row.kits_tags || []).map((t) => (
            <Chip key={t} label={t} size="small" variant="outlined" sx={{ fontSize: 9, height: 18 }} />
          ))}
        </Box>
      ),
    },
    {
      field: 'app_count', headerName: 'Приложений', width: 120,
      renderCell: (p) => (
        <span>
          {p.row.app_count}
          <span style={{ fontSize: 10, color: '#94A3B8', marginLeft: 4 }}>
            (L0{p.row.l0_count}/L1{p.row.l1_count}/L2{p.row.l2_count})
          </span>
        </span>
      ),
    },
    { field: 'status', headerName: 'Статус', width: 120, renderCell: (p) => <StatusChip status={p.row.status} /> },
    {
      field: 'created_by', headerName: 'IT-лидер', width: 150,
      renderCell: (p) => <span style={{ fontSize: 12 }}>{p.row.created_by || '—'}</span>,
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
    <ErrorBoundary viewName="Projects Registry">
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        <PageHeader
          title="Реестр проектов"
          subtitle={`${projects.length} проектов`}
          action={
            <Box sx={{ display: 'flex', gap: 1 }}>
              <Button size="small" onClick={fetchProjects} disabled={loading} startIcon={<Refresh />} sx={{ textTransform: 'none' }}>
                Обновить
              </Button>
              <Button size="small" onClick={() => setSimpleCreateOpen(true)} sx={{ textTransform: 'none' }}>
                Быстрое создание
              </Button>
              <Button size="small" variant="contained" startIcon={<Add />} onClick={() => setWizardOpen(true)}
                sx={{ textTransform: 'none', fontWeight: 600 }}>
                Создать проект
              </Button>
            </Box>
          }
        />

        {error && <Alert severity="error" onClose={() => setError(null)}>{error}</Alert>}

        {loading ? (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            {[1, 2, 3].map((i) => <Skeleton key={i} variant="rectangular" height={40} sx={{ borderRadius: 1 }} />)}
          </Box>
        ) : projects.length === 0 ? (
          <EmptyTable title="Нет проектов" description="Создайте первый проект." actionLabel="Создать проект" onAction={() => setWizardOpen(true)} />
        ) : (
          <DataGrid
            columns={columns} rows={projects} getRowId={(row) => row.id}
            density="compact" disableColumnMenu disableRowSelectionOnClick
            onRowClick={(params: GridRowParams<Project>) => onNavigate?.('project-detail', { projectId: params.row.id })}
            sx={{
              height: 520, border: '1px solid', borderColor: 'divider', borderRadius: 2,
              '& .MuiDataGrid-columnHeaders': { bgcolor: 'action.hover', fontWeight: 600, fontSize: 12 },
              '& .MuiDataGrid-row': { cursor: 'pointer' },
              '& .MuiDataGrid-cell': { fontSize: 12 },
            }}
          />
        )}

        <FormDialog
          open={simpleCreateOpen}
          onClose={() => setSimpleCreateOpen(false)}
          title="Создать новый проект"
          submitLabel="Создать"
          onSubmit={handleCreateProject}
          submitDisabled={!newName.trim()}
          submitting={submitting}
        >
          <TextField label="Название проекта" value={newName} onChange={(e) => setNewName(e.target.value)}
            size="small" fullWidth required autoFocus />
          <TextField label="Описание" value={newDescription} onChange={(e) => setNewDescription(e.target.value)}
            size="small" fullWidth multiline minRows={2} />
          <Box>
            <Typography variant="caption" sx={{ fontWeight: 600, display: 'block', mb: 0.5 }}>
              Теги КИТС
            </Typography>
            <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
              {kitsTags.map((kt) => (
                <Chip key={kt.id} label={kt.label} size="small"
                  variant={newKitsTags.includes(kt.id) ? 'filled' : 'outlined'}
                  color={newKitsTags.includes(kt.id) ? 'primary' : 'default'}
                  onClick={() => setNewKitsTags((prev) => prev.includes(kt.id) ? prev.filter((t) => t !== kt.id) : [...prev, kt.id])}
                  sx={{ cursor: 'pointer' }} />
              ))}
            </Box>
          </Box>
        </FormDialog>

        {/* POST-FLASH-001: Project Composition Wizard */}
        {wizardOpen && (
          <Box sx={{
            position: 'fixed', inset: 0, zIndex: 1300, bgcolor: 'background.default',
            overflowY: 'auto', p: 3,
          }}>
            <ProjectCreateWizard
              onComplete={() => { setWizardOpen(false); fetchProjects(); }}
              onCancel={() => setWizardOpen(false)}
            />
          </Box>
        )}
      </Box>
    </ErrorBoundary>
  );
}