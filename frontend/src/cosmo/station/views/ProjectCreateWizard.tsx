/**
 * POST-FLASH-001: ProjectCreateWizard — Multi-step project composition flow.
 *
 * Steps:
 *   1. Drag folders → auto-detect application candidates
 *   2. Review proposed apps, artifact kinds, levels
 *   3. Proposed dependency graph preview
 *   4. KITS tags, Project Team, Manifest toggle
 *   5. Validation + Create → result summary
 *
 * Supports: N folders → N apps → N+1 repos, partial failure reporting.
 */
import { useState, useCallback, useRef } from 'react';
import {
  Box, Typography, Button, Stepper, Step, StepLabel, TextField,
  Paper, Chip, Grid, Card, CardContent, Switch, FormControlLabel,
  Alert, CircularProgress, Select, MenuItem, Divider, IconButton, Tooltip,
} from '@mui/material';
import {
  CloudUpload, CheckCircle, Warning, Folder, Code, Hub,
  Add, Delete, ArrowForward, ArrowBack, Settings, Group, VpnKey,
} from '@mui/icons-material';
import { api, type ComposeFolder, type ComposeAppCandidate, type ProjectComposeResult } from '../api';
import { ErrorBoundary } from '../../shared/ErrorBoundary';
import { PageHeader } from '../minimal/PageHeader';
import { StatusChip } from '../minimal/StatusChip';
import { toast } from '../../shared/toast';

interface WizardProps {
  onComplete?: (result: ProjectComposeResult) => void;
  onCancel: () => void;
}

const ARTIFACT_KINDS = ['docker', 'jar', 'npm', 'pip', 'binary', 'helm', 'wasm'];
const APP_KINDS = ['microservice', 'gateway', 'frontend', 'library', 'database', 'broker'];
const TEAM_ROLES = ['it_leader', 'developer', 'secops', 'devops', 'qa'] as const;
const KITS_OPTIONS = ['cbr', 'payments', 'cards', 'auth', 'gateway', 'logging'];

export function ProjectCreateWizard({ onComplete, onCancel }: WizardProps) {
  const [activeStep, setActiveStep] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<ProjectComposeResult | null>(null);
  const [validationErrors, setValidationErrors] = useState<string[]>([]);

  // Step 0: Project basics
  const [projectName, setProjectName] = useState('');
  const [projectDescription, setProjectDescription] = useState('');

  // Step 1: Folders → app candidates (drag-and-drop simulation)
  const [folders, setFolders] = useState<ComposeFolder[]>([
    { name: 'api-gateway', path: 'src/gateway', proposed_apps: [{ name: 'api-gateway', kind: 'gateway', level: 1, repo_path: 'org/api-gateway', branch: 'main', artifact_kind: 'docker' }] },
    { name: 'auth-service', path: 'src/auth', proposed_apps: [{ name: 'auth-service', kind: 'microservice', level: 1, repo_path: 'org/auth-service', branch: 'main', artifact_kind: 'docker' }] },
  ]);
  const [dragActive, setDragActive] = useState(false);

  // Step 2: Proposed graph (dependencies between apps)
  const [graphEdges, setGraphEdges] = useState<Array<{ from: string; to: string }>>([]);

  // Step 3: KITS tags + Team + Manifest
  const [kitsTags, setKitsTags] = useState<string[]>([]);
  const [teamMembers, setTeamMembers] = useState<Array<{ name: string; email: string; role: string }>>([
    { name: '', email: '', role: 'it_leader' },
  ]);
  const [enableManifest, setEnableManifest] = useState(true);
  const [artifactKind, setArtifactKind] = useState('docker');

  const steps = [
    'Проект',
    'Папки → Приложения',
    'Граф зависимостей',
    'KITS / Команда / Manifest',
    'Валидация и создание',
  ];

  const allApps = folders.flatMap((f) => f.proposed_apps);
  const appNames = new Set(allApps.map((a) => a.name));

  // ── Folder drag-and-drop ──────────────────────────────────────────

  const handleDragOver = (e: React.DragEvent) => { e.preventDefault(); setDragActive(true); };
  const handleDragLeave = () => setDragActive(false);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(false);
    const folderName = e.dataTransfer.getData('text/plain') || `folder-${folders.length + 1}`;
    const newFolder: ComposeFolder = {
      name: folderName,
      path: `src/${folderName}`,
      proposed_apps: [{
        name: folderName, kind: 'microservice', level: 1,
        repo_path: `org/${folderName}`,
        branch: 'main',
        artifact_kind: 'docker',
      }],
    };
    setFolders((prev) => [...prev, newFolder]);
  };

  const handleAddFolder = () => {
    const idx = folders.length + 1;
    setFolders((prev) => [...prev, {
      name: `service-${idx}`, path: `src/service-${idx}`,
      proposed_apps: [{
        name: `service-${idx}`, kind: 'microservice', level: 1,
        repo_path: `org/service-${idx}`,
        branch: 'main',
        artifact_kind: 'docker',
      }],
    }]);
  };

  const handleRemoveFolder = (idx: number) => {
    setFolders((prev) => prev.filter((_, i) => i !== idx));
  };

  const handleUpdateCandidate = (folderIdx: number, candidateIdx: number, patch: Partial<ComposeAppCandidate>) => {
    setFolders((prev) => prev.map((f, fi) => fi === folderIdx ? {
      ...f,
      proposed_apps: f.proposed_apps.map((a, ai) => ai === candidateIdx ? { ...a, ...patch } : a),
    } : f));
  };

  const handleAddCandidate = (folderIdx: number) => {
    setFolders((prev) => prev.map((f, fi) => fi === folderIdx ? {
      ...f,
      proposed_apps: [...f.proposed_apps, {
        name: `${f.name}-lib`, kind: 'library' as const, level: 0,
        repo_path: `org/${f.name}-lib`, branch: 'main', artifact_kind: 'npm',
      }],
    } : f));
  };

  // ── Team ───────────────────────────────────────────────────────────

  const handleAddTeamMember = () => {
    setTeamMembers((prev) => [...prev, { name: '', email: '', role: 'developer' }]);
  };

  const handleUpdateTeamMember = (idx: number, field: string, value: string) => {
    setTeamMembers((prev) => prev.map((m, i) => i === idx ? { ...m, [field]: value } : m));
  };

  const handleRemoveTeamMember = (idx: number) => {
    setTeamMembers((prev) => prev.filter((_, i) => i !== idx));
  };

  // ── Validation ─────────────────────────────────────────────────────

  const validate = useCallback((): string[] => {
    const errs: string[] = [];
    if (!projectName.trim()) errs.push('Название проекта обязательно');
    if (folders.length === 0) errs.push('Добавьте хотя бы одну папку');
    // KITS tags are optional per POST-FLASH-002
    const filledTeam = teamMembers.filter((m) => m.name.trim() || m.email.trim());
    if (filledTeam.length > 0 && filledTeam.some((m) => !m.name.trim() || !m.email.trim())) {
      errs.push('У всех участников команды должны быть заполнены имя и email');
    }
    return errs;
  }, [projectName, folders, teamMembers]);

  // ── Create Project ─────────────────────────────────────────────────

  const handleCreate = async () => {
    const errs = validate();
    if (errs.length > 0) { setValidationErrors(errs); return; }
    setSubmitting(true);
    setValidationErrors([]);
    try {
      const res = await api.createProjectCompose({
        name: projectName.trim(),
        description: projectDescription.trim() || undefined,
        kits_tags: kitsTags,
        folders,
        team: teamMembers.filter((m) => m.name.trim()).map((m) => ({
          name: m.name.trim(), email: m.email.trim(),
          role: m.role as 'it_leader' | 'developer' | 'secops' | 'devops' | 'qa',
        })),
        enable_manifest: enableManifest,
        artifact_kind: artifactKind,
      });
      setResult(res);
      toast.success(`Проект "${res.project_name}" создан: ${res.apps_created} приложений, ${res.repos_created} репозиториев`);
      onComplete?.(res);
    } catch (err: unknown) {
      const msg = (err as Error)?.message || 'Ошибка создания проекта';
      setValidationErrors([msg]);
      toast.error(msg);
    } finally {
      setSubmitting(false);
    }
  };

  // ── Render ─────────────────────────────────────────────────────────

  if (result) {
    return (
      <ErrorBoundary viewName="Project Create Result">
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, py: 4, textAlign: 'center' }}>
          <CheckCircle sx={{ fontSize: 64, color: 'success.main', mx: 'auto' }} />
          <Typography variant="h5" sx={{ fontWeight: 700 }}>Проект создан</Typography>
          <Typography variant="body1" color="text.secondary">
            {result.project_name} · {result.apps_created} приложений · {result.repos_created} репозиториев
          </Typography>
          <Paper variant="outlined" sx={{ p: 2, maxWidth: 500, mx: 'auto', borderRadius: 2 }}>
            {result.apps.map((a) => (
              <Box key={a.app_id} sx={{ display: 'flex', justifyContent: 'space-between', py: 0.5 }}>
                <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>{a.app_id}</Typography>
                <StatusChip status={a.status} />
              </Box>
            ))}
          </Paper>
          {result.validation_errors && result.validation_errors.length > 0 && (
            <Alert severity="warning">
              {result.validation_errors.map((e, i) => <div key={i}>{e}</div>)}
            </Alert>
          )}
          <Box sx={{ display: 'flex', gap: 1, justifyContent: 'center' }}>
            <Button variant="contained" onClick={() => onComplete?.(result)} sx={{ textTransform: 'none', fontWeight: 600 }}>
              Перейти к проекту
            </Button>
          </Box>
        </Box>
      </ErrorBoundary>
    );
  }

  return (
    <ErrorBoundary viewName="Project Create Wizard">
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        <PageHeader title="Создание проекта" subtitle={`Шаг ${activeStep + 1} из ${steps.length}`} action={<Button size="small" variant="outlined" onClick={onCancel} sx={{ textTransform: 'none' }}>Отмена</Button>} />

        <Stepper activeStep={activeStep} alternativeLabel sx={{ mb: 2 }}>
          {steps.map((label) => <Step key={label}><StepLabel>{label}</StepLabel></Step>)}
        </Stepper>

        {validationErrors.length > 0 && (
          <Alert severity="error" onClose={() => setValidationErrors([])}>
            {validationErrors.map((e, i) => <div key={i}>• {e}</div>)}
          </Alert>
        )}

        {/* ═══ Step 0: Project Basics ═══ */}
        {activeStep === 0 && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, maxWidth: 600 }}>
            <TextField label="Название проекта" value={projectName} onChange={(e) => setProjectName(e.target.value)}
              size="small" fullWidth required autoFocus placeholder="Digital Ruble Platform" />
            <TextField label="Описание" value={projectDescription} onChange={(e) => setProjectDescription(e.target.value)}
              size="small" fullWidth multiline minRows={2} placeholder="Опциональное описание проекта" />
          </Box>
        )}

        {/* ═══ Step 1: Folders → App candidates ═══ */}
        {activeStep === 1 && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <Typography variant="body2" color="text.secondary">
              Перетащите папки или добавьте вручную. Для каждой папки будет предложено приложение.
            </Typography>

            {/* Drop zone */}
            <Paper
              variant="outlined"
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              sx={{
                p: 4, borderRadius: 2, textAlign: 'center', cursor: 'copy',
                borderStyle: 'dashed', borderWidth: 2,
                borderColor: dragActive ? 'primary.main' : 'divider',
                bgcolor: dragActive ? 'action.hover' : 'background.paper',
                transition: 'all 0.15s',
              }}
            >
              <CloudUpload sx={{ fontSize: 36, color: 'text.disabled', mb: 1 }} />
              <Typography variant="body2" color="text.secondary">
                {dragActive ? 'Отпустите для добавления папки' : 'Перетащите папки сюда или нажмите «Добавить»'}
              </Typography>
            </Paper>

            {/* Folder list */}
            {folders.map((folder, fi) => (
              <Card key={fi} variant="outlined" sx={{ borderRadius: 2 }}>
                <CardContent sx={{ p: 2 }}>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1.5 }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <Folder sx={{ color: 'warning.main', fontSize: 20 }} />
                      <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>{folder.name}</Typography>
                      <Chip label={folder.path} size="small" variant="outlined" sx={{ fontFamily: 'monospace', fontSize: 10 }} />
                    </Box>
                    <Box sx={{ display: 'flex', gap: 0.5 }}>
                      <Tooltip title="Добавить приложение"><IconButton size="small" onClick={() => handleAddCandidate(fi)}><Add sx={{ fontSize: 16 }} /></IconButton></Tooltip>
                      <Tooltip title="Удалить папку"><IconButton size="small" color="error" onClick={() => handleRemoveFolder(fi)}><Delete sx={{ fontSize: 16 }} /></IconButton></Tooltip>
                    </Box>
                  </Box>

                  {folder.proposed_apps.map((app, ai) => (
                    <Paper key={ai} variant="outlined" sx={{ p: 1.5, mb: 1, borderRadius: 1.5, bgcolor: 'action.hover' }}>
                      <Grid container spacing={1} sx={{ alignItems: 'center' }}>
                        <Grid size={{ xs: 12, sm: 4 }}>
                          <TextField size="small" label="Название" value={app.name}
                            onChange={(e) => handleUpdateCandidate(fi, ai, { name: e.target.value })} fullWidth />
                        </Grid>
                        <Grid size={{ xs: 6, sm: 3 }}>
                          <Select size="small" value={app.kind}
                            onChange={(e) => handleUpdateCandidate(fi, ai, { kind: e.target.value as ComposeAppCandidate['kind'] })} fullWidth>
                            {APP_KINDS.map((k) => <MenuItem key={k} value={k}>{k}</MenuItem>)}
                          </Select>
                        </Grid>
                        <Grid size={{ xs: 6, sm: 2 }}>
                          <Select size="small" value={app.level} onChange={(e) => handleUpdateCandidate(fi, ai, { level: Number(e.target.value) })} fullWidth>
                            <MenuItem value={0}>L0</MenuItem><MenuItem value={1}>L1</MenuItem><MenuItem value={2}>L2</MenuItem>
                          </Select>
                        </Grid>
                        <Grid size={{ xs: 12, sm: 3 }}>
                          <TextField size="small" label="Repo" value={app.repo_path}
                            onChange={(e) => handleUpdateCandidate(fi, ai, { repo_path: e.target.value })} fullWidth />
                        </Grid>
                      </Grid>
                      <Box sx={{ mt: 1, display: 'flex', gap: 1, alignItems: 'center' }}>
                        <Select size="small" value={app.artifact_kind || 'docker'}
                          onChange={(e) => handleUpdateCandidate(fi, ai, { artifact_kind: e.target.value })} sx={{ minWidth: 120 }}>
                          {ARTIFACT_KINDS.map((k) => <MenuItem key={k} value={k}>{k}</MenuItem>)}
                        </Select>
                        <Typography variant="caption" color="text.secondary">Artifact kind</Typography>
                      </Box>
                    </Paper>
                  ))}
                </CardContent>
              </Card>
            ))}

            <Button variant="outlined" size="small" startIcon={<Add />} onClick={handleAddFolder} sx={{ textTransform: 'none' }}>
              Добавить папку
            </Button>
          </Box>
        )}

        {/* ═══ Step 2: Proposed Graph ═══ */}
        {activeStep === 2 && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <Typography variant="body2" color="text.secondary">
              Укажите зависимости между приложениями. Выберите from → to.
            </Typography>

            {/* Add edge form */}
            <Paper variant="outlined" sx={{ p: 2, borderRadius: 2, display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
              <Select size="small" value="" onChange={(e) => {
                if (!e.target.value) return;
                const [from, to] = (e.target.value as string).split('→');
                if (from && to && !graphEdges.some((ge) => ge.from === from && ge.to === to)) {
                  setGraphEdges((prev) => [...prev, { from, to }]);
                }
              }} displayEmpty sx={{ minWidth: 260 }}>
                <MenuItem value="">+ Добавить зависимость...</MenuItem>
                {allApps.flatMap((a) =>
                  allApps.filter((b) => b.name !== a.name).map((b) => (
                    <MenuItem key={`${a.name}→${b.name}`} value={`${a.name}→${b.name}`}>
                      {a.name} → {b.name}
                    </MenuItem>
                  ))
                )}
              </Select>
            </Paper>

            {/* Edges list */}
            {graphEdges.length === 0 ? (
              <Typography variant="body2" color="text.disabled" sx={{ textAlign: 'center', py: 4 }}>
                Зависимости не указаны. Приложения независимы.
              </Typography>
            ) : (
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
                {graphEdges.map((edge, i) => (
                  <Paper key={i} variant="outlined" sx={{ p: 1, display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderRadius: 1.5 }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <Chip label={edge.from} size="small" sx={{ fontWeight: 600, fontFamily: 'monospace' }} />
                      <ArrowForward sx={{ color: 'text.disabled', fontSize: 16 }} />
                      <Chip label={edge.to} size="small" variant="outlined" sx={{ fontFamily: 'monospace' }} />
                    </Box>
                    <IconButton size="small" color="error" onClick={() => setGraphEdges((prev) => prev.filter((_, j) => j !== i))}>
                      <Delete sx={{ fontSize: 14 }} />
                    </IconButton>
                  </Paper>
                ))}
              </Box>
            )}

            {/* Visual graph preview */}
            {graphEdges.length > 0 && (
              <Card variant="outlined" sx={{ borderRadius: 2, p: 3, textAlign: 'center' }}>
                <Hub sx={{ fontSize: 28, color: 'primary.main', mb: 1 }} />
                <Typography variant="body2" sx={{ fontWeight: 600 }}>
                  Предполагаемый граф: {allApps.length} узлов, {graphEdges.length} рёбер
                </Typography>
                <Box sx={{ mt: 2, display: 'flex', justifyContent: 'center', gap: 2, flexWrap: 'wrap' }}>
                  {allApps.map((a) => (
                    <Paper key={a.name} variant="outlined" sx={{ p: 1, borderRadius: 1, borderColor: 'primary.light' }}>
                      <Typography variant="caption" sx={{ fontWeight: 700 }}>{a.name}</Typography>
                    </Paper>
                  ))}
                </Box>
              </Card>
            )}
          </Box>
        )}

        {/* ═══ Step 3: KITS Tags + Team + Manifest ═══ */}
        {activeStep === 3 && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {/* KITS Tags */}
            <Card variant="outlined" sx={{ borderRadius: 2 }}>
              <CardContent>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5 }}>
                  <VpnKey sx={{ color: 'text.secondary', fontSize: 18 }} />
                  <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>Теги КИТС (опционально)</Typography>
                </Box>
                <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                  {KITS_OPTIONS.map((k) => (
                    <Chip key={k} label={k} size="small"
                      variant={kitsTags.includes(k) ? 'filled' : 'outlined'}
                      color={kitsTags.includes(k) ? 'primary' : 'default'}
                      onClick={() => setKitsTags((prev) => prev.includes(k) ? prev.filter((x) => x !== k) : [...prev, k])}
                      sx={{ cursor: 'pointer' }} />
                  ))}
                </Box>
              </CardContent>
            </Card>

            {/* Project Team */}
            <Card variant="outlined" sx={{ borderRadius: 2 }}>
              <CardContent>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1.5 }}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <Group sx={{ color: 'text.secondary', fontSize: 18 }} />
                    <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>Project Team</Typography>
                  </Box>
                  <Button size="small" onClick={handleAddTeamMember} startIcon={<Add />} sx={{ textTransform: 'none', fontSize: 11 }}>
                    Добавить
                  </Button>
                </Box>
                {teamMembers.map((m, i) => (
                  <Box key={i} sx={{ display: 'flex', gap: 1, mb: 1 }}>
                    <TextField size="small" placeholder="Имя" value={m.name}
                      onChange={(e) => handleUpdateTeamMember(i, 'name', e.target.value)} sx={{ flex: 1 }} />
                    <TextField size="small" placeholder="email" value={m.email}
                      onChange={(e) => handleUpdateTeamMember(i, 'email', e.target.value)} sx={{ flex: 1 }} />
                    <Select size="small" value={m.role} onChange={(e) => handleUpdateTeamMember(i, 'role', e.target.value)} sx={{ minWidth: 120 }}>
                      {TEAM_ROLES.map((r) => <MenuItem key={r} value={r}>{r}</MenuItem>)}
                    </Select>
                    {teamMembers.length > 1 && (
                      <IconButton size="small" color="error" onClick={() => handleRemoveTeamMember(i)}><Delete sx={{ fontSize: 16 }} /></IconButton>
                    )}
                  </Box>
                ))}
              </CardContent>
            </Card>

            {/* Manifest toggle + artifact kind */}
            <Card variant="outlined" sx={{ borderRadius: 2 }}>
              <CardContent>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5 }}>
                  <Settings sx={{ color: 'text.secondary', fontSize: 18 }} />
                  <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>Project Manifest</Typography>
                </Box>
                <FormControlLabel
                  control={<Switch checked={enableManifest} onChange={(_, v) => setEnableManifest(v)} />}
                  label="Автоматически сгенерировать Project Manifest"
                />
                <Box sx={{ mt: 1.5 }}>
                  <Typography variant="caption" sx={{ fontWeight: 600, display: 'block', mb: 0.5 }}>Artifact kind по умолчанию</Typography>
                  <Select size="small" value={artifactKind} onChange={(e) => setArtifactKind(e.target.value)} sx={{ minWidth: 140 }}>
                    {ARTIFACT_KINDS.map((k) => <MenuItem key={k} value={k}>{k}</MenuItem>)}
                  </Select>
                </Box>
              </CardContent>
            </Card>
          </Box>
        )}

        {/* ═══ Step 4: Validation + Create ═══ */}
        {activeStep === 4 && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <Typography variant="body2" color="text.secondary">
              Проверьте итоговую конфигурацию перед созданием проекта.
            </Typography>

            <Card variant="outlined" sx={{ borderRadius: 2 }}>
              <CardContent>
                <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1.5 }}>Сводка</Typography>
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, fontSize: 13 }}>
                  <div><strong>Название:</strong> {projectName || '—'}</div>
                  <div><strong>Папок:</strong> {folders.length} · <strong>Приложений:</strong> {allApps.length}</div>
                  <div><strong>Репозиториев:</strong> {allApps.length} (по одному на приложение)</div>
                  <div><strong>КИТС:</strong> {kitsTags.length > 0 ? kitsTags.join(', ') : '—'}</div>
                  <div><strong>Команда:</strong> {teamMembers.filter((m) => m.name.trim()).length} участников</div>
                  <div><strong>Manifest:</strong> {enableManifest ? 'Включён' : 'Отключён'}</div>
                  <div><strong>Artifact kind:</strong> {artifactKind}</div>
                  <div><strong>Зависимостей:</strong> {graphEdges.length}</div>
                </Box>
              </CardContent>
            </Card>

            {validationErrors.length === 0 && (
              <Alert severity="info" sx={{ fontSize: 12 }}>
                Будет создано {allApps.length} репозиториев (по одному на приложение). При наличии общих библиотек количество репозиториев может увеличиться.
              </Alert>
            )}
          </Box>
        )}

        {/* Navigation buttons */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 2 }}>
          <Button onClick={() => setActiveStep((prev) => prev - 1)} disabled={activeStep === 0}
            startIcon={<ArrowBack />} sx={{ textTransform: 'none' }}>
            Назад
          </Button>
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Button onClick={onCancel} sx={{ textTransform: 'none' }}>Отмена</Button>
            {activeStep < steps.length - 1 ? (
              <Button variant="contained" endIcon={<ArrowForward />}
                onClick={() => setActiveStep((prev) => prev + 1)}
                disabled={activeStep === 0 && !projectName.trim()}
                sx={{ textTransform: 'none', fontWeight: 600 }}>
                Далее
              </Button>
            ) : (
              <Button variant="contained" color="success" startIcon={<CheckCircle />}
                onClick={handleCreate} disabled={submitting}
                sx={{ textTransform: 'none', fontWeight: 700 }}>
                {submitting ? <CircularProgress size={16} sx={{ mr: 1 }} /> : null}
                {submitting ? 'Создание...' : 'Создать проект'}
              </Button>
            )}
          </Box>
        </Box>
      </Box>
    </ErrorBoundary>
  );
}