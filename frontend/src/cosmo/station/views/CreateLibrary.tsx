/**
 * POST-FLASH-001: Library Creation — public library with consumer/producer roles.
 *
 * Consumers: read/build/deploy
 * Library Team: write/settings only
 */
import { useState } from 'react';
import {
  Box, Typography, Button, TextField, Select, MenuItem,
  Paper, Alert, CircularProgress, Chip, Grid, IconButton,
  Card, CardContent,
} from '@mui/material';
import { Add, Delete, Visibility, Lock, CheckCircle } from '@mui/icons-material';
import { api, type Application } from '../api';
import { ErrorBoundary } from '../../shared/ErrorBoundary';
import { PageHeader } from '../minimal/PageHeader';
import { toast } from '../../shared/toast';

interface LibraryCreateProps {
  onComplete?: (app: Application) => void;
  onCancel: () => void;
}

export function CreateLibrary({ onComplete, onCancel }: LibraryCreateProps) {
  const [libId, setLibId] = useState('');
  const [libName, setLibName] = useState('');
  const [repoPath, setRepoPath] = useState('');
  const [branch, setBranch] = useState('main');
  const [description, setDescription] = useState('');
  const [visibility, setVisibility] = useState<'internal' | 'public'>('internal');
  const [teamMembers, setTeamMembers] = useState<Array<{ name: string; email: string; role: string }>>([
    { name: '', email: '', role: 'it_leader' },
  ]);
  const [submitting, setSubmitting] = useState(false);
  const [created, setCreated] = useState<Application | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleCreate = async () => {
    if (!libId.trim() || !repoPath.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const app = await api.createPublicLibrary({
        id: libId.trim(),
        name: libName.trim() || libId.trim(),
        repo_path: repoPath.trim(),
        branch: branch.trim() || 'main',
        description: description.trim() || undefined,
        team: teamMembers.filter((m) => m.name.trim()).map((m) => ({
          name: m.name.trim(), email: m.email.trim(),
          role: m.role as 'it_leader' | 'developer' | 'secops' | 'devops' | 'qa',
        })),
        visibility,
      });
      setCreated(app);
      toast.success(`Библиотека ${app.id} создана`);
      onComplete?.(app);
    } catch (err: unknown) {
      const msg = (err as Error)?.message || 'Ошибка создания библиотеки';
      setError(msg);
      toast.error(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const handleAddMember = () => {
    setTeamMembers((prev) => [...prev, { name: '', email: '', role: 'developer' }]);
  };

  const handleUpdateMember = (idx: number, field: string, value: string) => {
    setTeamMembers((prev) => prev.map((m, i) => i === idx ? { ...m, [field]: value } : m));
  };

  const handleRemoveMember = (idx: number) => {
    setTeamMembers((prev) => prev.filter((_, i) => i !== idx));
  };

  if (created) {
    return (
      <ErrorBoundary viewName="Library Created">
        <Box sx={{ py: 4, textAlign: 'center', display: 'flex', flexDirection: 'column', gap: 2 }}>
          <CheckCircle sx={{ fontSize: 64, color: 'success.main', mx: 'auto' }} />
          <Typography variant="h5" sx={{ fontWeight: 700 }}>Библиотека создана</Typography>
          <Paper variant="outlined" sx={{ p: 2, maxWidth: 400, mx: 'auto', borderRadius: 2 }}>
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, fontSize: 12 }}>
              <div><strong>ID:</strong> {created.id}</div>
              <div><strong>Repo:</strong> {created.repo_binding.repo_path}</div>
              <div><strong>Visibility:</strong> {visibility === 'public' ? 'Публичная' : 'Внутренняя'}</div>
            </Box>
          </Paper>
          <Button variant="contained" onClick={() => onComplete?.(created)} sx={{ textTransform: 'none', fontWeight: 600, mx: 'auto' }}>
            Продолжить
          </Button>
        </Box>
      </ErrorBoundary>
    );
  }

  return (
    <ErrorBoundary viewName="Create Library">
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, maxWidth: 700 }}>
        <PageHeader
          title="Создать публичную библиотеку"
          subtitle="Профиль доступа: read/build/deploy для потребителей, write/settings — только для Library Team."
          action={<Button size="small" variant="outlined" onClick={onCancel} sx={{ textTransform: 'none' }}>Отмена</Button>}
        />

        {error && <Alert severity="error" onClose={() => setError(null)}>{error}</Alert>}

        {/* Basic info */}
        <Paper variant="outlined" sx={{ p: 2, borderRadius: 2, display: 'flex', flexDirection: 'column', gap: 2 }}>
          <TextField label="Library ID" value={libId} onChange={(e) => setLibId(e.target.value)}
            size="small" fullWidth required autoFocus placeholder="lib-auth" />
          <TextField label="Отображаемое имя" value={libName} onChange={(e) => setLibName(e.target.value)}
            size="small" fullWidth placeholder="Auth Library" />
          <TextField label="Репозиторий (org/repo)" value={repoPath} onChange={(e) => setRepoPath(e.target.value)}
            size="small" fullWidth required placeholder="org/auth-lib" />
          <TextField label="Ветка" value={branch} onChange={(e) => setBranch(e.target.value)}
            size="small" fullWidth />
          <TextField label="Описание" value={description} onChange={(e) => setDescription(e.target.value)}
            size="small" fullWidth multiline minRows={2} placeholder="Shared authentication utilities" />
        </Paper>

        {/* Visibility */}
        <Card variant="outlined" sx={{ borderRadius: 2 }}>
          <CardContent>
            <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1.5 }}>Видимость</Typography>
            <Grid container spacing={1}>
              <Grid size={{ xs: 6 }}>
                <Paper variant="outlined"
                  onClick={() => setVisibility('internal')}
                  sx={{
                    p: 2, cursor: 'pointer', borderRadius: 1.5, textAlign: 'center',
                    borderColor: visibility === 'internal' ? 'primary.main' : 'divider',
                    borderWidth: visibility === 'internal' ? 2 : 1,
                    bgcolor: visibility === 'internal' ? 'action.selected' : 'background.paper',
                  }}>
                  <Lock sx={{ fontSize: 24, color: 'primary.main', mb: 0.5 }} />
                  <Typography variant="body2" sx={{ fontWeight: 600 }}>Internal</Typography>
                  <Typography variant="caption" color="text.secondary">Только КИТС-проекты</Typography>
                </Paper>
              </Grid>
              <Grid size={{ xs: 6 }}>
                <Paper variant="outlined"
                  onClick={() => setVisibility('public')}
                  sx={{
                    p: 2, cursor: 'pointer', borderRadius: 1.5, textAlign: 'center',
                    borderColor: visibility === 'public' ? 'success.main' : 'divider',
                    borderWidth: visibility === 'public' ? 2 : 1,
                    bgcolor: visibility === 'public' ? 'action.selected' : 'background.paper',
                  }}>
                  <Visibility sx={{ fontSize: 24, color: 'success.main', mb: 0.5 }} />
                  <Typography variant="body2" sx={{ fontWeight: 600 }}>Public</Typography>
                  <Typography variant="caption" color="text.secondary">Все организации</Typography>
                </Paper>
              </Grid>
            </Grid>
          </CardContent>
        </Card>

        {/* Library Team */}
        <Card variant="outlined" sx={{ borderRadius: 2 }}>
          <CardContent>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1.5 }}>
              <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>Library Team (write/settings)</Typography>
              <Button size="small" startIcon={<Add />} onClick={handleAddMember} sx={{ textTransform: 'none', fontSize: 11 }}>
                Добавить
              </Button>
            </Box>
            <Alert severity="info" sx={{ fontSize: 11, mb: 1.5 }}>
              Library Team имеет права write/settings. Все остальные — read/build/deploy.
            </Alert>
            {teamMembers.map((m, i) => (
              <Box key={i} sx={{ display: 'flex', gap: 1, mb: 1 }}>
                <TextField size="small" placeholder="Имя" value={m.name}
                  onChange={(e) => handleUpdateMember(i, 'name', e.target.value)} sx={{ flex: 1 }} />
                <TextField size="small" placeholder="email" value={m.email}
                  onChange={(e) => handleUpdateMember(i, 'email', e.target.value)} sx={{ flex: 1 }} />
                <Select size="small" value={m.role} onChange={(e) => handleUpdateMember(i, 'role', e.target.value)} sx={{ minWidth: 120 }}>
                  {['it_leader', 'developer', 'secops', 'devops', 'qa'].map((r) => <MenuItem key={r} value={r}>{r}</MenuItem>)}
                </Select>
                {teamMembers.length > 1 && (
                  <IconButton size="small" color="error" onClick={() => handleRemoveMember(i)}><Delete sx={{ fontSize: 16 }} /></IconButton>
                )}
              </Box>
            ))}
          </CardContent>
        </Card>

        {/* Permissions legend */}
        <Paper variant="outlined" sx={{ p: 2, borderRadius: 2, display: 'flex', gap: 3 }}>
          <Box>
            <Chip icon={<Lock sx={{ fontSize: 10 }} />} label="Library Team" size="small" color="primary" variant="outlined" sx={{ fontSize: 10 }} />
            <Typography variant="caption" sx={{ display: 'block', mt: 0.5, fontSize: 10 }}>
              read · build · deploy · write · settings
            </Typography>
          </Box>
          <Box>
            <Chip icon={<Visibility sx={{ fontSize: 10 }} />} label="Consumers" size="small" color="success" variant="outlined" sx={{ fontSize: 10 }} />
            <Typography variant="caption" sx={{ display: 'block', mt: 0.5, fontSize: 10 }}>
              read · build · deploy
            </Typography>
          </Box>
        </Paper>

        {/* Actions */}
        <Box sx={{ display: 'flex', gap: 1, justifyContent: 'flex-end' }}>
          <Button onClick={onCancel} sx={{ textTransform: 'none' }}>Отмена</Button>
          <Button variant="contained" startIcon={submitting ? <CircularProgress size={16} /> : <Add />}
            onClick={handleCreate} disabled={submitting || !libId.trim() || !repoPath.trim()}
            sx={{ textTransform: 'none', fontWeight: 600 }}>
            {submitting ? 'Создание...' : 'Создать библиотеку'}
          </Button>
        </Box>
      </Box>
    </ErrorBoundary>
  );
}