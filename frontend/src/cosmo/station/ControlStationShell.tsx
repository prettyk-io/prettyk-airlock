/**
 * OWN-FLASH-001: Control Station Shell — KITS & Projects workspace.
 *
 * Routes:
 *   overview           — ProjectsOverview (KITS switcher)
 *   projects-registry  — ProjectsRegistry (create/manage)
 *   project-detail     — ProjectDetail (Data Grid + Team)
 *   project-graph      — ProjectGraph (React Flow)
 *   flat-apps          — FlatAppsRegistry (filterable)
 *   release-types      — ReleaseTypeBuilder
 *   batch-constructor  — BatchConstructor
 *   release-dashboard  — ProjectReleaseDashboard
 *   applications       — Applications (legacy)
 *   pipelines / runs / gates / releases / builds / deployments
 */
import { useState, useEffect } from 'react';
import {
  Box, AppBar, Toolbar, Typography, IconButton, Drawer, List, ListItemButton, ListItemIcon, ListItemText,
  Divider, Chip, Tooltip, Button,
} from '@mui/material';
import {
  Dashboard, Apps, AccountTree, PlayArrow, Gavel,
  DarkMode, LightMode, Notifications, Person, RocketLaunch, Search,
  Build, CloudUpload, Folder, Settings,
} from '@mui/icons-material';
import { useCosmoTheme } from '../theme';
import { usePreference } from '../shared/usePreference';
import type { IDEContext } from '../shared/DeepLinker';

import { ProjectsOverview } from './views/ProjectsOverview';
import { ProjectsRegistry } from './views/ProjectsRegistry';
import { ProjectDetail } from './views/ProjectDetail';
import { ProjectGraph } from './views/ProjectGraph';
import { FlatAppsRegistry } from './views/FlatAppsRegistry';
import { ReleaseTypeBuilder } from './views/ReleaseTypeBuilder';
import { BatchConstructor } from './views/BatchConstructor';
import { ProjectReleaseDashboard } from './views/ProjectReleaseDashboard';
import { ProjectCreateWizard } from './views/ProjectCreateWizard';
import { CreateStandaloneApp } from './views/CreateStandaloneApp';
import { CreateLibrary } from './views/CreateLibrary';
import { Applications } from './views/Applications';
import { PipelineStudio } from './views/PipelineStudio';
import { RunControl } from './views/RunControl';
import { RunComparison } from './views/RunComparison';
import { Gates } from './views/Gates';
import { Releases } from './views/Releases';
import { Catalog } from './views/Catalog';
import { GatePolicyBuilder } from './views/GatePolicyBuilder';
import { BuildsRegistry } from './views/BuildsRegistry';
import { DeploymentsRegistry } from './views/DeploymentsRegistry';
import { AlertHUD } from './views/AlertHUD';

import { Breadcrumbs } from '../shared/Breadcrumbs';
import { GlobalSearch } from '../shared/GlobalSearch';
import { ToastContainer } from '../shared/ToastContainer';
import { useHotkeys } from '../shared/useHotkeys';
import { HotkeyOverlay } from '../shared/HotkeyOverlay';

interface ControlStationProps {
  view?: string;
  runId?: string;
  onNavigateToIDE?: (ctx: Partial<IDEContext>) => void;
}

const NAV_ITEMS = [
  { id: 'overview',           label: 'Обзор',        icon: <Dashboard /> },
  { id: 'projects-registry',  label: 'Проекты',       icon: <Folder /> },
  { id: 'applications',       label: 'Приложения',    icon: <Apps /> },
  { id: 'builds',             label: 'Сборки',        icon: <Build /> },
  { id: 'deployments',        label: 'Деплои',        icon: <CloudUpload /> },
  { id: 'pipelines',          label: 'Пайплайны',     icon: <AccountTree /> },
  { id: 'runs',               label: 'Прогоны',       icon: <PlayArrow /> },
  { id: 'gates',              label: 'Гейты',         icon: <Gavel /> },
  { id: 'releases',           label: 'Релизы',        icon: <RocketLaunch /> },
] as const;

const DRAWER_WIDTH = 240;

export function ControlStationShell({ view, runId, onNavigateToIDE }: ControlStationProps) {
  const { mode, toggleMode } = useCosmoTheme();
  const [nav, setNav] = usePreference('nav');
  const [searchOpen, setSearchOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [projectId, setProjectId] = useState<string>('');

  // COS-099: Global keyboard navigation
  useHotkeys(
    (targetView) => { setNav(targetView); },
    () => {},
    () => { setSearchOpen(false); setHelpOpen(false); }
  );

  // COS-024
  useEffect(() => { if (view) setNav(view); }, [view]);

  // COS-057: ⌘K
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setSearchOpen((prev) => !prev);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const openInIDE = (ctx: { repo: string; file: string; line?: number }) => {
    onNavigateToIDE?.(ctx);
  };

  const handleSearchResultSelect = (targetView: string, params?: Record<string, string>) => {
    setNav(targetView);
    if (params?.projectId) { setProjectId(params.projectId); setNav('project-detail'); }
  };

  const handleNavigate = (targetView: string, params?: Record<string, string>) => {
    if (params?.projectId) { setProjectId(params.projectId); setNav(targetView); return; }
    setNav(targetView);
  };

  const currentViewTitle = NAV_ITEMS.find((n) => n.id === nav)?.label || nav;

  const renderCurrentView = () => {
    switch (nav) {
      case 'overview':
        return <ProjectsOverview onNavigate={handleNavigate} />;
      case 'projects-registry':
        return <ProjectsRegistry onNavigate={handleNavigate} />;
      case 'project-detail':
        return <ProjectDetail projectId={projectId} onBack={() => setNav('overview')} onNavigate={handleNavigate} />;
      case 'project-graph':
        return <ProjectGraph projectId={projectId} onBack={() => setNav('project-detail')} />;
      case 'flat-apps':
        return <FlatAppsRegistry onNavigate={handleNavigate} />;
      case 'release-types':
        return <ReleaseTypeBuilder />;
      case 'batch-constructor':
        return <BatchConstructor projectId={projectId} onBack={() => setNav('project-detail')} />;
      case 'release-dashboard':
        return <ProjectReleaseDashboard projectId={projectId} onBack={() => setNav('project-detail')} />;
      case 'project-create':
        return <ProjectCreateWizard onComplete={() => setNav('overview')} onCancel={() => setNav('projects-registry')} />;
      case 'app-create-standalone':
        return <CreateStandaloneApp onComplete={() => setNav('flat-apps')} onCancel={() => setNav('flat-apps')} />;
      case 'library-create':
        return <CreateLibrary onComplete={() => setNav('flat-apps')} onCancel={() => setNav('flat-apps')} />;
      case 'applications':
        return <Applications onNavigateToIDE={openInIDE} />;
      case 'builds':
        return <BuildsRegistry />;
      case 'deployments':
        return <DeploymentsRegistry />;
      case 'pipelines':
        return <PipelineStudio onNavigateToIDE={openInIDE} onNavigateToView={setNav} />;
      case 'catalog':
        return <Catalog />;
      case 'runs':
        return <RunControl initialRunId={runId} onNavigateToIDE={openInIDE} onNavigateToView={setNav} />;
      case 'compare':
        return <RunComparison />;
      case 'gates':
        return <Gates onNavigateToIDE={openInIDE} onNavigateToPolicyBuilder={() => setNav('gate-policy-builder')} />;
      case 'gate-policy-builder':
        return <GatePolicyBuilder />;
      case 'releases':
        return <Releases onNavigateToIDE={openInIDE} />;
      default:
        return <ProjectsOverview onNavigate={handleNavigate} />;
    }
  };

  const deepLinkChip = runId ? (
    <Chip icon={<PlayArrow />} label={`Run #${runId}`} size="small" color="info" variant="outlined"
      onDelete={() => {}} sx={{ fontSize: 11, height: 24 }} />
  ) : null;

  return (
    <Box className="cosmo-control-station" sx={{ display: 'flex', minHeight: '100vh' }}>
      <Drawer variant="permanent" sx={{ width: DRAWER_WIDTH, flexShrink: 0, '& .MuiDrawer-paper': { width: DRAWER_WIDTH, boxSizing: 'border-box' } }}>
        <Box sx={{ p: 2, display: 'flex', alignItems: 'center', gap: 1 }}>
          <Box sx={{ width: 32, height: 32, borderRadius: 1, background: 'linear-gradient(135deg, #0ea5e9, #7c3aed)' }} />
          <Typography variant="h6" sx={{ fontWeight: 700, fontSize: 16 }}>Cosmoport</Typography>
        </Box>
        <Divider />
        <List sx={{ p: 1 }}>
          {NAV_ITEMS.map((item) => (
            <ListItemButton key={item.id} selected={nav === item.id} onClick={() => setNav(item.id)}
              sx={{ borderRadius: 2, mb: 0.5 }}>
              <ListItemIcon sx={{ minWidth: 36 }}>{item.icon}</ListItemIcon>
              <ListItemText primary={item.label} />
            </ListItemButton>
          ))}
        </List>
      </Drawer>

      <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        <AppBar position="static" color="transparent" elevation={0} sx={{ borderBottom: 1, borderColor: 'divider' }}>
          <Toolbar sx={{ gap: 1.5, minHeight: 48, px: 2 }}>
            <Breadcrumbs viewTitle={currentViewTitle} onNavigateToView={setNav} />

            <div style={{ flex: 1 }} />

            <Button variant="outlined" size="small" startIcon={<Search sx={{ fontSize: 16 }} />}
              onClick={() => setSearchOpen(true)}
              sx={{ textTransform: 'none', fontSize: 12, color: 'text.secondary', borderColor: 'divider',
                bgcolor: 'action.hover', px: 1.5, py: 0.5, borderRadius: 2, display: { xs: 'none', sm: 'inline-flex' } }}>
              <span>Поиск по системе...</span>
              <kbd style={{ marginLeft: 8, padding: '1px 5px', borderRadius: 4, background: 'rgba(0,0,0,0.08)', fontSize: 10, fontFamily: 'monospace' }}>⌘K</kbd>
            </Button>

            <span style={{ padding: '2px 8px', borderRadius: 6, fontSize: 11, background: 'rgba(14,165,233,0.1)', color: '#0EA5E9', border: '1px solid rgba(14,165,233,0.2)', fontWeight: 600 }}>Active Control Plane</span>
            {deepLinkChip}

            <AlertHUD onNavigateToView={(targetView, params) => {
              setNav(targetView);
              if (params?.projectId) setProjectId(params.projectId);
            }} />
            <Tooltip title={mode === 'dark' ? 'Включить светлую тему (Meta Light)' : 'Включить тёмную тему (Meta Dark)'}>
              <IconButton size="small" onClick={toggleMode} aria-label="theme-toggle"
                sx={{ color: mode === 'dark' ? '#FBBF24' : 'text.secondary', transition: 'color 0.2s ease' }}>
                {mode === 'dark' ? <LightMode fontSize="small" /> : <DarkMode fontSize="small" />}
              </IconButton>
            </Tooltip>
            <span style={{ padding: '2px 8px', borderRadius: 6, fontSize: 11, background: 'rgba(148,163,184,0.1)', color: '#64748B', border: '1px solid rgba(148,163,184,0.2)', display: 'flex', alignItems: 'center', gap: 4 }}>
              <Person style={{ fontSize: 14 }} /> Operator
            </span>
          </Toolbar>
        </AppBar>

        <Box sx={{ flex: 1, p: 3, overflowY: 'auto' }}>
          {renderCurrentView()}
        </Box>
      </Box>

      <GlobalSearch open={searchOpen} onClose={() => setSearchOpen(false)} onSelectResult={handleSearchResultSelect} />
      <HotkeyOverlay open={helpOpen || nav === 'help'} onClose={() => { setHelpOpen(false); setNav('overview'); }} />
      <ToastContainer />
    </Box>
  );
}