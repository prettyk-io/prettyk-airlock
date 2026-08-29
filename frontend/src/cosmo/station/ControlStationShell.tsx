/**
 * COS-021/COS-022/COS-057: Control Station Shell — MUI Minimal UI + Meta Light.
 *
 * Router views:
 *   - domains / overview -> Overview.tsx
 *   - applications       -> Applications.tsx
 *   - topology           -> AppGraph.tsx
 *   - pipelines          -> PipelineStudio.tsx
 *   - runs               -> RunControl.tsx
 *   - gates              -> Gates.tsx
 *   - releases           -> Releases.tsx
 *   - catalog            -> Catalog.tsx
 *   - audit              -> AuditLog.tsx
 *   - evidence           -> Evidence.tsx
 *
 * COS-057: Breadcrumbs & Global Search (⌘K).
 */
import { useState, useEffect } from 'react';
import {
  Box, AppBar, Toolbar, Typography, IconButton, Drawer, List, ListItemButton, ListItemIcon, ListItemText,
  Divider, Chip, Tooltip, Button,
} from '@mui/material';
import {
  Dashboard, Apps, AccountTree, PlayArrow, Gavel, Store, History, Settings,
  DarkMode, LightMode, Notifications, Person, RocketLaunch, Hub, Fingerprint, Search, Compare, TrendingUp,
} from '@mui/icons-material';
import { useCosmoTheme } from '../theme';
import { usePreference } from '../shared/usePreference';
import type { IDEContext } from '../shared/DeepLinker';

import { Overview } from './views/Overview';
import { Applications } from './views/Applications';
import { AppGraph } from './views/AppGraph';
import { PipelineStudio } from './views/PipelineStudio';
import { RunControl } from './views/RunControl';
import { RunComparison } from './views/RunComparison';
import { Gates } from './views/Gates';
import { Releases } from './views/Releases';
import { Catalog } from './views/Catalog';
import { Evidence } from './views/Evidence';
import { AuditLog } from './views/AuditLog';
import { Analytics } from './views/Analytics';
import { GatePolicyBuilder } from './views/GatePolicyBuilder';
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
  { id: 'domains', label: 'Домены', icon: <Dashboard /> },
  { id: 'applications', label: 'Приложения', icon: <Apps /> },
  { id: 'topology', label: 'Топология', icon: <Hub /> },
  { id: 'pipelines', label: 'Пайплайны', icon: <AccountTree /> },
  { id: 'runs', label: 'Прогоны', icon: <PlayArrow /> },
  { id: 'compare', label: 'Сравнение', icon: <Compare /> },
  { id: 'analytics', label: 'Аналитика', icon: <TrendingUp /> },
  { id: 'gates', label: 'Гейты', icon: <Gavel /> },
  { id: 'releases', label: 'Релизы', icon: <RocketLaunch /> },
  { id: 'catalog', label: 'Каталог', icon: <Store /> },
  { id: 'audit', label: 'Аудит', icon: <History /> },
  { id: 'evidence', label: 'Доказательства', icon: <Fingerprint /> },
  { id: 'settings', label: 'Настройки', icon: <Settings /> },
] as const;

const DRAWER_WIDTH = 240;

const selStyle: React.CSSProperties = {
  padding: '4px 8px', borderRadius: 6, border: '1px solid #CBD5E1',
  background: 'transparent', fontSize: 13, fontFamily: 'inherit',
  color: 'inherit', minWidth: 110, outline: 'none',
};

export function ControlStationShell({ view, runId, onNavigateToIDE }: ControlStationProps) {
  const { mode, toggleMode } = useCosmoTheme();
  const [nav, setNav] = usePreference('nav');
  const [domain, setDomain] = usePreference('domain');
  const [env, setEnv] = usePreference('env');
  const [searchOpen, setSearchOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [newRunOpen, setNewRunOpen] = useState(false);

  // COS-099: Global keyboard navigation
  useHotkeys(
    (targetView) => {
      setNav(targetView);
    },
    () => {
      setNewRunOpen(true);
    },
    () => {
      setSearchOpen(false);
      setHelpOpen(false);
      setNewRunOpen(false);
    }
  );

  // COS-024: синхронизировать nav при deep-link
  useEffect(() => {
    if (view) setNav(view);
  }, [view]);

  // COS-057: Глобальный хоткей ⌘K / Ctrl+K
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

  // COS-024: Deep-link run context display
  const deepLinkChip = runId ? (
    <Chip
      icon={<PlayArrow />}
      label={`Run #${runId}`}
      size="small"
      color="info"
      variant="outlined"
      onDelete={() => { /* clear deep-link */ }}
      sx={{ fontSize: 11, height: 24 }}
    />
  ) : null;

  // COS-024: Transition to Web IDE (e.g., from Gate Inspector → code)
  const openInIDE = (ctx: { repo: string; file: string; line?: number }) => {
    if (onNavigateToIDE) {
      onNavigateToIDE(ctx);
    }
  };

  const handleSearchResultSelect = (targetView: string, params?: Record<string, string>) => {
    setNav(targetView);
    if (params?.domain_id) {
      setDomain(params.domain_id);
    }
  };

  const currentViewTitle = NAV_ITEMS.find((n) => n.id === nav)?.label || nav;

  const renderCurrentView = () => {
    switch (nav) {
      case 'domains':
      case 'overview':
        return <Overview selectedDomain={domain} onNavigateToView={setNav} onNavigateToIDE={openInIDE} />;
      case 'help':
        return <Overview selectedDomain={domain} onNavigateToView={setNav} onNavigateToIDE={openInIDE} />;
      case 'applications':
        return <Applications selectedDomain={domain} onNavigateToIDE={openInIDE} />;
      case 'topology':
        return <AppGraph selectedDomain={domain} onNavigateToIDE={openInIDE} />;
      case 'pipelines':
        return <PipelineStudio onNavigateToIDE={openInIDE} onNavigateToView={setNav} />;
      case 'runs':
        return <RunControl selectedDomain={domain} initialRunId={runId} onNavigateToIDE={openInIDE} onNavigateToView={setNav} />;
      case 'compare':
        return <RunComparison />;
      case 'analytics':
        return <Analytics selectedDomain={domain} />;
      case 'gates':
        return <Gates onNavigateToIDE={openInIDE} onNavigateToPolicyBuilder={() => setNav('gate-policy-builder')} />;
      case 'gate-policy-builder':
        return <GatePolicyBuilder />;
      case 'releases':
        return <Releases selectedDomain={domain} onNavigateToIDE={openInIDE} />;
      case 'catalog':
        return <Catalog />;
      case 'audit':
        return <AuditLog />;
      case 'evidence':
        return <Evidence initialRunId={runId} onNavigateToIDE={openInIDE} />;
      case 'settings':
        return <Overview selectedDomain={domain} onNavigateToView={setNav} onNavigateToIDE={openInIDE} />;
      default:
        return <Overview selectedDomain={domain} onNavigateToView={setNav} onNavigateToIDE={openInIDE} />;
    }
  };

  return (
    <Box className="cosmo-control-station" sx={{ display: 'flex', minHeight: '100vh' }}>
      {/* Sidebar */}
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

      {/* Main */}
      <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        {/* Header */}
        <AppBar position="static" color="transparent" elevation={0} sx={{ borderBottom: 1, borderColor: 'divider' }}>
          <Toolbar sx={{ gap: 1.5, minHeight: 48, px: 2 }}>
            {/* COS-057: Breadcrumbs */}
            <Breadcrumbs
              domain={domain}
              viewTitle={currentViewTitle}
              onNavigateToView={setNav}
              onSelectDomain={setDomain}
            />

            <div style={{ flex: 1 }} />

            {/* Global Search Button */}
            <Button
              variant="outlined"
              size="small"
              startIcon={<Search sx={{ fontSize: 16 }} />}
              onClick={() => setSearchOpen(true)}
              sx={{
                textTransform: 'none',
                fontSize: 12,
                color: 'text.secondary',
                borderColor: 'divider',
                bgcolor: 'action.hover',
                px: 1.5,
                py: 0.5,
                borderRadius: 2,
                display: { xs: 'none', sm: 'inline-flex' },
              }}
            >
              <span>Поиск по системе...</span>
              <kbd style={{ marginLeft: 8, padding: '1px 5px', borderRadius: 4, background: 'rgba(0,0,0,0.08)', fontSize: 10, fontFamily: 'monospace' }}>
                ⌘K
              </kbd>
            </Button>

            <select value={domain} onChange={(e) => setDomain(e.target.value)} style={selStyle}>
              <option value="all">Все домены</option>
              <option value="cbr">Цифровой рубль</option>
              <option value="payments">Платежи</option>
            </select>
            <select value={env} onChange={(e) => setEnv(e.target.value)} style={selStyle}>
              <option value="dev">dev</option>
              <option value="test">test</option>
              <option value="stage">stage</option>
              <option value="prod">prod</option>
            </select>
            <span style={{ padding: '2px 8px', borderRadius: 6, fontSize: 11, background: 'rgba(14,165,233,0.1)', color: '#0EA5E9', border: '1px solid rgba(14,165,233,0.2)', fontWeight: 600 }}>Active Control Plane</span>
            {deepLinkChip}

            <AlertHUD onNavigateToView={(targetView, params) => {
              setNav(targetView);
              if (params?.domain_id) setDomain(params.domain_id);
            }} />
            <Tooltip title={mode === 'dark' ? 'Включить светлую тему (Meta Light)' : 'Включить тёмную тему (Meta Dark)'}>
              <IconButton
                size="small"
                onClick={toggleMode}
                aria-label="theme-toggle"
                sx={{
                  color: mode === 'dark' ? '#FBBF24' : 'text.secondary',
                  transition: 'color 0.2s ease',
                }}
              >
                {mode === 'dark' ? <LightMode fontSize="small" /> : <DarkMode fontSize="small" />}
              </IconButton>
            </Tooltip>
            <span style={{ padding: '2px 8px', borderRadius: 6, fontSize: 11, background: 'rgba(148,163,184,0.1)', color: '#64748B', border: '1px solid rgba(148,163,184,0.2)', display: 'flex', alignItems: 'center', gap: 4 }}>
              <Person style={{ fontSize: 14 }} /> Operator
            </span>
          </Toolbar>
        </AppBar>

        {/* View container */}
        <Box sx={{ flex: 1, p: 3, overflowY: 'auto' }}>
          {renderCurrentView()}
        </Box>
      </Box>

      {/* COS-057: Global Search Modal */}
      <GlobalSearch
        open={searchOpen}
        onClose={() => setSearchOpen(false)}
        onSelectResult={handleSearchResultSelect}
      />

      {/* COS-099: Keyboard Shortcuts Help Overlay */}
      <HotkeyOverlay
        open={helpOpen || nav === 'help'}
        onClose={() => { setHelpOpen(false); setNav('domains'); }}
      />

      {/* Toast Notification Container */}
      <ToastContainer />
    </Box>
  );
}
