/**
 * COS-057: Global Search & Command Palette (⌘K).
 *
 * Fast multi-entity search across Domains, Apps, Runs, Gates, Releases, Bricks, and Views.
 */
import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  Dialog, DialogContent, Box, TextField, Typography, Chip,
  InputAdornment, IconButton, List, ListItemButton, ListItemIcon,
  ListItemText, Paper,
} from '@mui/material';
import {
  Search, Close, Dashboard, Apps, AccountTree, PlayArrow,
  Gavel, RocketLaunch, Store, History, Hub, Fingerprint,
  Code, Folder, Security,
} from '@mui/icons-material';
import { api, type Domain, type Application, type Run, type Gate, type Release, type PipelineBrick } from '../station/api';

export interface SearchResultItem {
  id: string;
  title: string;
  subtitle?: string;
  category: 'views' | 'domains' | 'apps' | 'runs' | 'gates' | 'releases' | 'bricks';
  viewId: string;
  params?: Record<string, string>;
  icon: React.ReactNode;
}

const STATIC_VIEWS: SearchResultItem[] = [
  { id: 'v-domains', title: 'Обзор и Домены', subtitle: 'Дашборд и сводка КИТС', category: 'views', viewId: 'domains', icon: <Dashboard sx={{ fontSize: 18, color: '#0EA5E9' }} /> },
  { id: 'v-apps', title: 'Приложения и группы', subtitle: 'Иерархия сервисов L0/L1/L2', category: 'views', viewId: 'applications', icon: <Apps sx={{ fontSize: 18, color: '#38BDF8' }} /> },
  { id: 'v-topo', title: 'Редактор топологии', subtitle: 'Визуальный граф связей компонентов', category: 'views', viewId: 'topology', icon: <Hub sx={{ fontSize: 18, color: '#A855F7' }} /> },
  { id: 'v-pipes', title: 'Pipeline Studio & DAG', subtitle: 'Компилятор планов и шаги DAG', category: 'views', viewId: 'pipelines', icon: <AccountTree sx={{ fontSize: 18, color: '#F59E0B' }} /> },
  { id: 'v-runs', title: 'Run Control Plane', subtitle: 'Управление прогонами и батчами', category: 'views', viewId: 'runs', icon: <PlayArrow sx={{ fontSize: 18, color: '#10B981' }} /> },
  { id: 'v-gates', title: 'Security Gates', subtitle: 'Инспектор вердиктов и политик', category: 'views', viewId: 'gates', icon: <Gavel sx={{ fontSize: 18, color: '#EF4444' }} /> },
  { id: 'v-rels', title: 'Управление Релизами', subtitle: 'Трансфер ЗР → ЗТ → ЗПЭ', category: 'views', viewId: 'releases', icon: <RocketLaunch sx={{ fontSize: 18, color: '#EC4899' }} /> },
  { id: 'v-cat', title: 'Каталог кирпичей', subtitle: 'Библиотека Pipeline Bricks', category: 'views', viewId: 'catalog', icon: <Store sx={{ fontSize: 18, color: '#6366F1' }} /> },
  { id: 'v-audit', title: 'Журнал аудита', subtitle: 'Аудит действий пользователей и безопасности', category: 'views', viewId: 'audit', icon: <History sx={{ fontSize: 18, color: '#64748B' }} /> },
  { id: 'v-evid', title: 'Журнал доказательств', subtitle: 'Криптографический реестр SHA-256', category: 'views', viewId: 'evidence', icon: <Fingerprint sx={{ fontSize: 18, color: '#14B8A6' }} /> },
];

interface GlobalSearchProps {
  open: boolean;
  onClose: () => void;
  onSelectResult: (viewId: string, params?: Record<string, string>) => void;
}

export function GlobalSearch({ open, onClose, onSelectResult }: GlobalSearchProps) {
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);

  // Entities cache
  const [domains, setDomains] = useState<Domain[]>([]);
  const [apps, setApps] = useState<Application[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [gates, setGates] = useState<Gate[]>([]);
  const [releases, setReleases] = useState<Release[]>([]);
  const [bricks, setBricks] = useState<PipelineBrick[]>([]);

  const inputRef = useRef<HTMLInputElement>(null);

  // Fetch all entities once opened
  useEffect(() => {
    if (open) {
      setQuery('');
      setSelectedIndex(0);
      Promise.all([
        api.getDomains().catch(() => []),
        api.getApps().catch(() => []),
        api.getRuns().catch(() => []),
        api.getGates().catch(() => []),
        api.getReleases().catch(() => []),
        api.getBricks().catch(() => []),
      ]).then(([d, a, r, g, rel, b]) => {
        setDomains(d || []);
        setApps(a || []);
        setRuns(r || []);
        setGates(g || []);
        setReleases(rel || []);
        setBricks(b || []);
      });
    }
  }, [open]);

  // Aggregate search index
  const allItems = useMemo<SearchResultItem[]>(() => {
    const list: SearchResultItem[] = [...STATIC_VIEWS];

    domains.forEach((d) => {
      list.push({
        id: `dom-${d.id}`,
        title: d.label,
        subtitle: `Домен / КИТС ID: ${d.id}`,
        category: 'domains',
        viewId: 'domains',
        params: { domain_id: d.id },
        icon: <AccountTree sx={{ fontSize: 18, color: '#0EA5E9' }} />,
      });
    });

    apps.forEach((a) => {
      list.push({
        id: `app-${a.id}`,
        title: a.id,
        subtitle: `${a.level === 0 ? 'L0 Библиотека' : `L${a.level} Приложение`} · ${a.repo_binding.repo_path}`,
        category: 'apps',
        viewId: 'applications',
        params: { app_id: a.id },
        icon: a.level === 0 ? <Code sx={{ fontSize: 18, color: '#A855F7' }} /> : <Apps sx={{ fontSize: 18, color: '#0EA5E9' }} />,
      });
    });

    runs.forEach((r) => {
      list.push({
        id: `run-${r.id}`,
        title: `Run #${r.id}`,
        subtitle: `План: ${r.plan_id} · Статус: ${r.status}`,
        category: 'runs',
        viewId: 'runs',
        params: { run_id: r.id },
        icon: <PlayArrow sx={{ fontSize: 18, color: '#10B981' }} />,
      });
    });

    gates.forEach((g) => {
      list.push({
        id: `gate-${g.id}`,
        title: `Gate ${g.id}`,
        subtitle: `Тип: ${g.type} · Решение: ${g.decision || 'ожидание'}`,
        category: 'gates',
        viewId: 'gates',
        params: { gate_id: g.id },
        icon: <Gavel sx={{ fontSize: 18, color: '#EF4444' }} />,
      });
    });

    releases.forEach((rel) => {
      list.push({
        id: `rel-${rel.id}`,
        title: rel.name,
        subtitle: `Версия: ${rel.version} · Зона: ${rel.zone}`,
        category: 'releases',
        viewId: 'releases',
        params: { release_id: rel.id },
        icon: <RocketLaunch sx={{ fontSize: 18, color: '#EC4899' }} />,
      });
    });

    bricks.forEach((b) => {
      list.push({
        id: `brick-${b.id}`,
        title: b.name,
        subtitle: `Тип: ${b.type.toUpperCase()} · ${b.id}`,
        category: 'bricks',
        viewId: 'catalog',
        params: { brick_id: b.id },
        icon: <Security sx={{ fontSize: 18, color: '#F59E0B' }} />,
      });
    });

    return list;
  }, [domains, apps, runs, gates, releases, bricks]);

  // Filtered results
  const filteredResults = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return allItems.slice(0, 8); // Top views
    return allItems.filter(
      (item) =>
        item.title.toLowerCase().includes(q) ||
        item.id.toLowerCase().includes(q) ||
        (item.subtitle && item.subtitle.toLowerCase().includes(q))
    ).slice(0, 15);
  }, [query, allItems]);

  const handleSelect = useCallback(
    (item: SearchResultItem) => {
      onSelectResult(item.viewId, item.params);
      onClose();
    },
    [onSelectResult, onClose]
  );

  // Keyboard navigation (ArrowDown, ArrowUp, Enter, Esc)
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex((prev) => (prev + 1 < filteredResults.length ? prev + 1 : 0));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex((prev) => (prev - 1 >= 0 ? prev - 1 : filteredResults.length - 1));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (filteredResults[selectedIndex]) {
        handleSelect(filteredResults[selectedIndex]);
      }
    } else if (e.key === 'Escape') {
      onClose();
    }
  };

  const getCategoryLabel = (cat: string) => {
    switch (cat) {
      case 'views':
        return 'Раздел';
      case 'domains':
        return 'КИТС';
      case 'apps':
        return 'Сервис';
      case 'runs':
        return 'Прогон';
      case 'gates':
        return 'Gate';
      case 'releases':
        return 'Релиз';
      case 'bricks':
        return 'Brick';
      default:
        return cat;
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="sm"
      fullWidth
      slotProps={{
        paper: {
          sx: {
            borderRadius: 3,
            bgcolor: 'background.paper',
            boxShadow: '0 20px 40px rgba(0,0,0,0.3)',
            overflow: 'hidden',
            mt: -12,
          },
        },
      }}
    >
      <DialogContent sx={{ p: 0 }} onKeyDown={handleKeyDown}>
        {/* Search Input Bar */}
        <Box sx={{ p: 2, borderBottom: 1, borderColor: 'divider', display: 'flex', alignItems: 'center', gap: 1 }}>
          <TextField
            inputRef={inputRef}
            autoFocus
            placeholder="Поиск по доменам, приложениям, прогонам, гейтам, релизам (⌘K)..."
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelectedIndex(0);
            }}
            fullWidth
            variant="standard"
            slotProps={{
              input: {
                disableUnderline: true,
                startAdornment: (
                  <InputAdornment position="start">
                    <Search sx={{ color: 'primary.main', fontSize: 22 }} />
                  </InputAdornment>
                ),
                endAdornment: query ? (
                  <InputAdornment position="end">
                    <IconButton size="small" onClick={() => setQuery('')}>
                      <Close fontSize="small" />
                    </IconButton>
                  </InputAdornment>
                ) : null,
                sx: { fontSize: 14, fontWeight: 500 },
              },
            }}
          />
        </Box>

        {/* Results List */}
        <List sx={{ maxHeight: 420, overflowY: 'auto', p: 1 }}>
          {filteredResults.length === 0 ? (
            <Box sx={{ p: 4, textAlign: 'center', color: 'text.secondary' }}>
              <Typography variant="body2">Ничего не найдено по запросу «{query}»</Typography>
            </Box>
          ) : (
            filteredResults.map((item, index) => {
              const isSelected = selectedIndex === index;
              return (
                <ListItemButton
                  key={item.id}
                  selected={isSelected}
                  onClick={() => handleSelect(item)}
                  onMouseEnter={() => setSelectedIndex(index)}
                  sx={{
                    borderRadius: 2,
                    mb: 0.5,
                    px: 1.5,
                    py: 1,
                    transition: 'all 0.1s ease',
                  }}
                >
                  <ListItemIcon sx={{ minWidth: 32 }}>{item.icon}</ListItemIcon>
                  <ListItemText
                    primary={
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        <Typography variant="body2" sx={{ fontWeight: 600 }}>
                          {item.title}
                        </Typography>
                        <Chip
                          label={getCategoryLabel(item.category)}
                          size="small"
                          variant="outlined"
                          sx={{ fontSize: 9, height: 16, textTransform: 'uppercase' }}
                        />
                      </Box>
                    }
                    secondary={
                      item.subtitle && (
                        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', fontSize: 11 }}>
                          {item.subtitle}
                        </Typography>
                      )
                    }
                  />
                  <Typography variant="caption" color="text.disabled" sx={{ fontSize: 10, fontFamily: 'monospace' }}>
                    ↵
                  </Typography>
                </ListItemButton>
              );
            })
          )}
        </List>

        {/* Footer info */}
        <Box sx={{ p: 1.5, bgcolor: 'action.hover', borderTop: 1, borderColor: 'divider', display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 11, color: 'text.secondary' }}>
          <span>Используйте <strong>↑</strong> <strong>↓</strong> для выбора, <strong>Enter</strong> для перехода</span>
          <span><strong>ESC</strong> для закрытия</span>
        </Box>
      </DialogContent>
    </Dialog>
  );
}
