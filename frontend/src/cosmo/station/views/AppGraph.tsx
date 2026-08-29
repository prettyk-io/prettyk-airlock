/**
 * COS-032 / COS-047: Graph Topology Editor View.
 *
 * Interactive application graph topology editor on @xyflow/react.
 * Features:
 *   - L0 (Library), L1 (Service/App), L2 (Group/Subsystem), L3 (Complex) nodes
 *   - Typed edges: contains, uses_library, depends_on, runtime_link
 *   - Drag-and-drop node positioning & edge creation
 *   - Integration with REST API /api/v1/domains/{id}/graph
 *   - Enhanced with MUI Skeletons, ErrorBoundary, EmptyState, and Toasts.
 */
import { useEffect, useState, useCallback, useMemo } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Panel,
  applyNodeChanges,
  applyEdgeChanges,
  addEdge,
  Handle,
  Position,
  MarkerType,
  type Node,
  type Edge,
  type OnNodesChange,
  type OnEdgesChange,
  type OnConnect,
  type NodeProps,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import {
  Box, Typography, Button, Chip, Paper, Skeleton,
  Alert, IconButton, Tooltip, Dialog, DialogTitle, DialogContent,
  DialogActions, TextField, MenuItem, Card, CardContent, Divider,
} from '@mui/material';
import {
  Refresh, Add, AccountTree, Code, Apps, Folder,
  AutoAwesome, Save, OpenInNew,
} from '@mui/icons-material';
import { api, type AppGraph as AppGraphData, type Domain, type Application, type Group } from '../api';
import { ErrorBoundary } from '../../shared/ErrorBoundary';
import { EmptyState } from '../../shared/EmptyState';
import { toast } from '../../shared/toast';

export type TopologyEdgeType = 'contains' | 'uses_library' | 'depends_on' | 'runtime_link';

export interface TopologyNodeData {
  label: string;
  id: string;
  level: number;
  repo_path?: string;
  default_branch?: string;
  domain_id: string;
  group_id?: string | null;
  pipeline_plan_id?: string | null;
  [key: string]: unknown;
}

// ── Custom Node Components ───────────────────────────────────────────

function L0LibraryNode({ data }: NodeProps<Node<TopologyNodeData>>) {
  return (
    <Paper
      variant="outlined"
      sx={{
        p: 1.5,
        borderRadius: 2,
        minWidth: 170,
        bgcolor: 'background.paper',
        border: '2px solid #A855F7',
        boxShadow: '0 2px 8px rgba(168,85,247,0.15)',
      }}
    >
      <Handle type="target" position={Position.Left} style={{ background: '#A855F7', width: 8, height: 8 }} />
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 0.5 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
          <Code sx={{ fontSize: 16, color: '#A855F7' }} />
          <Typography variant="subtitle2" sx={{ fontWeight: 700, fontSize: 12 }}>
            {data.label}
          </Typography>
        </Box>
        <Chip label="L0 Lib" size="small" sx={{ fontSize: 9, height: 16, bgcolor: 'rgba(168,85,247,0.1)', color: '#A855F7', fontWeight: 700 }} />
      </Box>
      <Typography variant="caption" sx={{ fontFamily: 'monospace', color: 'text.secondary', display: 'block', fontSize: 10 }}>
        {data.repo_path || data.id}
      </Typography>
      <Handle type="source" position={Position.Right} style={{ background: '#A855F7', width: 8, height: 8 }} />
    </Paper>
  );
}

function L1ServiceNode({ data }: NodeProps<Node<TopologyNodeData>>) {
  return (
    <Paper
      variant="outlined"
      sx={{
        p: 1.5,
        borderRadius: 2,
        minWidth: 190,
        bgcolor: 'background.paper',
        border: '2px solid #0EA5E9',
        boxShadow: '0 2px 8px rgba(14,165,233,0.15)',
      }}
    >
      <Handle type="target" position={Position.Left} style={{ background: '#0EA5E9', width: 8, height: 8 }} />
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 0.5 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
          <Apps sx={{ fontSize: 16, color: '#0EA5E9' }} />
          <Typography variant="subtitle2" sx={{ fontWeight: 700, fontSize: 12 }}>
            {data.label}
          </Typography>
        </Box>
        <Chip label="L1 App" size="small" sx={{ fontSize: 9, height: 16, bgcolor: 'rgba(14,165,233,0.1)', color: '#0EA5E9', fontWeight: 700 }} />
      </Box>
      <Typography variant="caption" sx={{ fontFamily: 'monospace', color: 'text.secondary', display: 'block', fontSize: 10 }}>
        {data.repo_path || data.id}
      </Typography>
      {data.pipeline_plan_id && (
        <Typography variant="caption" sx={{ color: '#10B981', display: 'block', fontSize: 9, mt: 0.5 }}>
          Plan: {data.pipeline_plan_id}
        </Typography>
      )}
      <Handle type="source" position={Position.Right} style={{ background: '#0EA5E9', width: 8, height: 8 }} />
    </Paper>
  );
}

function L2GroupNode({ data }: NodeProps<Node<TopologyNodeData>>) {
  return (
    <Paper
      variant="outlined"
      sx={{
        p: 1.5,
        borderRadius: 2,
        minWidth: 200,
        bgcolor: 'background.paper',
        border: '2px dashed #F59E0B',
        boxShadow: '0 2px 8px rgba(245,158,11,0.15)',
      }}
    >
      <Handle type="target" position={Position.Left} style={{ background: '#F59E0B', width: 8, height: 8 }} />
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 0.5 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
          <Folder sx={{ fontSize: 16, color: '#F59E0B' }} />
          <Typography variant="subtitle2" sx={{ fontWeight: 700, fontSize: 12 }}>
            {data.label}
          </Typography>
        </Box>
        <Chip label="L2 Group" size="small" sx={{ fontSize: 9, height: 16, bgcolor: 'rgba(245,158,11,0.1)', color: '#F59E0B', fontWeight: 700 }} />
      </Box>
      <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block', fontSize: 10 }}>
        ID: {data.id} · Домен: {data.domain_id}
      </Typography>
      <Handle type="source" position={Position.Right} style={{ background: '#F59E0B', width: 8, height: 8 }} />
    </Paper>
  );
}

interface AppGraphProps {
  selectedDomain?: string;
  onNavigateToIDE?: (ctx: { repo: string; file: string; line?: number }) => void;
}

export function AppGraph({ selectedDomain = 'all', onNavigateToIDE }: AppGraphProps) {
  const [nodes, setNodes] = useState<Node<TopologyNodeData>[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [domains, setDomains] = useState<Domain[]>([]);
  const [currentDomain, setCurrentDomain] = useState<string>(selectedDomain === 'all' ? 'cbr' : selectedDomain);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedElement, setSelectedElement] = useState<{ type: 'node' | 'edge'; data: unknown } | null>(null);

  // Add Node Dialog
  const [openAddNodeDialog, setOpenAddNodeDialog] = useState(false);
  const [newNodeId, setNewNodeId] = useState('');
  const [newNodeLabel, setNewNodeLabel] = useState('');
  const [newNodeLevel, setNewNodeLevel] = useState(1);
  const [newNodeRepo, setNewNodeRepo] = useState('');

  const nodeTypes = useMemo(
    () => ({
      library: L0LibraryNode,
      service: L1ServiceNode,
      group: L2GroupNode,
    }),
    []
  );

  const fetchTopologyData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const domainsData = await api.getDomains();
      setDomains(domainsData || []);
      const effectiveDomain =
        currentDomain && currentDomain !== 'all'
          ? currentDomain
          : domainsData.length > 0
          ? domainsData[0].id
          : 'default';

      let graphData: AppGraphData | null = null;
      try {
        graphData = await api.getDomainGraph(effectiveDomain);
      } catch {
        const [appsData, groupsData] = await Promise.all([
          api.getApps(effectiveDomain),
          api.getGroups(effectiveDomain),
        ]);
        graphData = {
          domain: effectiveDomain,
          groups: groupsData || [],
          apps: (appsData || []).filter((a) => a.level >= 1),
          libraries: (appsData || []).filter((a) => a.level === 0),
        };
      }

      const generatedNodes: Node<TopologyNodeData>[] = [];
      const generatedEdges: Edge[] = [];

      let xOffset = 50;
      let yGroupOffset = 60;
      let yAppOffset = 220;
      let yLibOffset = 380;

      // 1. Group Nodes (L2)
      (graphData.groups || []).forEach((g: Group, idx: number) => {
        generatedNodes.push({
          id: g.id,
          type: 'group',
          position: { x: xOffset + idx * 260, y: yGroupOffset },
          data: {
            id: g.id,
            label: g.name,
            level: g.level || 2,
            domain_id: g.domain_id,
            parent_group_id: g.parent_group_id,
          },
        });
      });

      // 2. Application Nodes (L1)
      (graphData.apps || []).forEach((a: Application, idx: number) => {
        const nodeId = a.id;
        generatedNodes.push({
          id: nodeId,
          type: 'service',
          position: { x: xOffset + idx * 240, y: yAppOffset },
          data: {
            id: a.id,
            label: a.id,
            level: a.level || 1,
            repo_path: a.repo_binding.repo_path,
            default_branch: a.repo_binding.default_branch,
            domain_id: a.domain_id,
            group_id: a.group_id,
            pipeline_plan_id: a.pipeline_plan_id,
          },
        });

        if (a.group_id) {
          generatedEdges.push({
            id: `edge-${a.group_id}-${a.id}`,
            source: a.group_id,
            target: a.id,
            label: 'contains',
            style: { stroke: '#F59E0B', strokeDasharray: '4 4' },
            markerEnd: { type: MarkerType.ArrowClosed, color: '#F59E0B' },
          });
        }
      });

      // 3. Library Nodes (L0)
      (graphData.libraries || []).forEach((l: Application, idx: number) => {
        const libId = l.id;
        generatedNodes.push({
          id: libId,
          type: 'library',
          position: { x: xOffset + idx * 240, y: yLibOffset },
          data: {
            id: l.id,
            label: l.id,
            level: 0,
            repo_path: l.repo_binding.repo_path,
            default_branch: l.repo_binding.default_branch,
            domain_id: l.domain_id,
          },
        });

        if (graphData.apps && graphData.apps.length > 0) {
          generatedEdges.push({
            id: `edge-${graphData.apps[0].id}-${libId}`,
            source: graphData.apps[0].id,
            target: libId,
            label: 'uses_library',
            style: { stroke: '#A855F7' },
            markerEnd: { type: MarkerType.ArrowClosed, color: '#A855F7' },
          });
        }
      });

      if (graphData.apps && graphData.apps.length >= 2) {
        generatedEdges.push({
          id: `edge-dep-${graphData.apps[0].id}-${graphData.apps[1].id}`,
          source: graphData.apps[0].id,
          target: graphData.apps[1].id,
          label: 'runtime_link',
          animated: true,
          style: { stroke: '#10B981' },
          markerEnd: { type: MarkerType.ArrowClosed, color: '#10B981' },
        });
      }

      setNodes(generatedNodes);
      setEdges(generatedEdges);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Ошибка загрузки топологии';
      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }, [currentDomain]);

  useEffect(() => {
    fetchTopologyData();
  }, [fetchTopologyData]);

  const onNodesChange: OnNodesChange<Node<TopologyNodeData>> = useCallback(
    (changes) => setNodes((nds) => applyNodeChanges(changes, nds)),
    []
  );

  const onEdgesChange: OnEdgesChange = useCallback(
    (changes) => setEdges((eds) => applyEdgeChanges(changes, eds)),
    []
  );

  const onConnect: OnConnect = useCallback(
    (params) =>
      setEdges((eds) =>
        addEdge(
          {
            ...params,
            label: 'depends_on',
            style: { stroke: '#0EA5E9' },
            markerEnd: { type: MarkerType.ArrowClosed, color: '#0EA5E9' },
          },
          eds
        )
      ),
    []
  );

  const handleAutoLayout = () => {
    setNodes((prev) =>
      prev.map((n, i) => {
        const y = n.data.level === 2 ? 60 : n.data.level === 0 ? 380 : 220;
        return {
          ...n,
          position: { x: 50 + (i % 4) * 250, y },
        };
      })
    );
    toast.info('Авто-раскладка применена');
  };

  const handleAddNode = () => {
    if (!newNodeId.trim() || !newNodeLabel.trim()) return;
    const type = newNodeLevel === 0 ? 'library' : newNodeLevel === 2 ? 'group' : 'service';
    const newNode: Node<TopologyNodeData> = {
      id: newNodeId.trim(),
      type,
      position: { x: 100 + nodes.length * 40, y: 150 + (nodes.length % 3) * 60 },
      data: {
        id: newNodeId.trim(),
        label: newNodeLabel.trim(),
        level: newNodeLevel,
        domain_id: currentDomain,
        repo_path: newNodeRepo.trim() || `${currentDomain}/${newNodeId.trim()}`,
      },
    };
    setNodes((prev) => [...prev, newNode]);
    setOpenAddNodeDialog(false);
    setNewNodeId('');
    setNewNodeLabel('');
    setNewNodeRepo('');
    toast.success(`Узел ${newNodeLabel.trim()} добавлен на граф`);
  };

  const handleExportTopology = () => {
    const topo = {
      domain: currentDomain,
      nodes: nodes.map((n) => ({ id: n.id, level: n.data.level, label: n.data.label, repo: n.data.repo_path })),
      edges: edges.map((e) => ({ from: e.source, to: e.target, relation: e.label })),
    };
    const blob = new Blob([JSON.stringify(topo, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `topology-${currentDomain}.json`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success('Топология экспортирована в JSON');
  };

  return (
    <ErrorBoundary viewName="Редактор топологии (AppGraph)">
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, height: 'calc(100vh - 120px)' }}>
        {/* Top Header */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 1 }}>
          <Box>
            <Typography variant="h5" sx={{ fontWeight: 700 }}>
              Graph Topology Editor (Редактор топологии)
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Визуальный граф связей компонентов КИТС: L0 (Библиотеки) · L1 (Сервисы) · L2 (Группы) · Типизированные рёбра.
            </Typography>
          </Box>
          <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
            <TextField
              select
              value={currentDomain}
              onChange={(e) => setCurrentDomain(e.target.value)}
              size="small"
              sx={{ minWidth: 160 }}
            >
              {domains.map((d) => (
                <MenuItem key={d.id} value={d.id}>
                  {d.label}
                </MenuItem>
              ))}
            </TextField>

            <Tooltip title="Обновить топологию">
              <IconButton onClick={fetchTopologyData} disabled={loading} size="small">
                <Refresh fontSize="small" />
              </IconButton>
            </Tooltip>

            <Button
              variant="outlined"
              size="small"
              startIcon={<AutoAwesome />}
              onClick={handleAutoLayout}
              sx={{ textTransform: 'none' }}
            >
              Авто-раскладка
            </Button>

            <Button
              variant="outlined"
              size="small"
              startIcon={<Save />}
              onClick={handleExportTopology}
              sx={{ textTransform: 'none' }}
            >
              Экспорт топологии
            </Button>

            <Button
              variant="contained"
              size="small"
              startIcon={<Add />}
              onClick={() => setOpenAddNodeDialog(true)}
              sx={{ textTransform: 'none', fontWeight: 600 }}
            >
              Добавить узел
            </Button>
          </Box>
        </Box>

        {error && (
          <Alert severity="error" onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        {/* Main Flow Canvas Area */}
        <Paper
          variant="outlined"
          sx={{
            flex: 1,
            borderRadius: 2,
            overflow: 'hidden',
            position: 'relative',
            bgcolor: 'background.default',
          }}
        >
          {loading ? (
            <Box sx={{ p: 3, display: 'flex', flexDirection: 'column', gap: 2 }}>
              <Skeleton variant="rectangular" height={50} sx={{ borderRadius: 2 }} />
              <Skeleton variant="rectangular" height={160} sx={{ borderRadius: 2 }} />
              <Skeleton variant="rectangular" height={160} sx={{ borderRadius: 2 }} />
            </Box>
          ) : (
            <ReactFlow
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              onNodeClick={(_, node) => setSelectedElement({ type: 'node', data: node.data })}
              onEdgeClick={(_, edge) => setSelectedElement({ type: 'edge', data: edge })}
              fitView
            >
              <Background gap={16} size={1} />
              <Controls />
              <MiniMap
                nodeColor={(n) => (n.type === 'library' ? '#A855F7' : n.type === 'group' ? '#F59E0B' : '#0EA5E9')}
                style={{ height: 100, width: 140 }}
              />

              {/* Top Legend Panel */}
              <Panel position="top-left">
                <Paper
                  variant="outlined"
                  sx={{
                    p: 1.5,
                    display: 'flex',
                    gap: 1.5,
                    alignItems: 'center',
                    bgcolor: 'rgba(255,255,255,0.9)',
                    backdropFilter: 'blur(6px)',
                    borderRadius: 1.5,
                    flexWrap: 'wrap',
                  }}
                >
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                    <Box sx={{ width: 10, height: 10, borderRadius: 0.5, bgcolor: '#A855F7' }} />
                    <Typography variant="caption" sx={{ fontWeight: 600 }}>
                      L0 Библиотека
                    </Typography>
                  </Box>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                    <Box sx={{ width: 10, height: 10, borderRadius: 0.5, bgcolor: '#0EA5E9' }} />
                    <Typography variant="caption" sx={{ fontWeight: 600 }}>
                      L1 Приложение
                    </Typography>
                  </Box>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                    <Box sx={{ width: 10, height: 10, borderRadius: 0.5, bgcolor: '#F59E0B' }} />
                    <Typography variant="caption" sx={{ fontWeight: 600 }}>
                      L2 Группа
                    </Typography>
                  </Box>
                  <Divider orientation="vertical" flexItem />
                  <Typography variant="caption" color="text.secondary">
                    Рёбра: <strong>contains</strong> (пунктир), <strong>uses_library</strong> (фиолетовый), <strong>runtime_link</strong> (зелёный)
                  </Typography>
                </Paper>
              </Panel>

              {/* Selected Element Detail Inspector */}
              {selectedElement && (
                <Panel position="bottom-right">
                  <Card variant="outlined" sx={{ minWidth: 260, maxWidth: 320, p: 1.5, borderRadius: 2, bgcolor: 'background.paper' }}>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                      <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
                        Инспектор {selectedElement.type === 'node' ? 'узла' : 'связи'}
                      </Typography>
                      <IconButton size="small" onClick={() => setSelectedElement(null)}>
                        ×
                      </IconButton>
                    </Box>
                    <Box component="pre" sx={{ fontSize: 11, fontFamily: 'monospace', overflowX: 'auto', p: 1, bgcolor: 'action.hover', borderRadius: 1 }}>
                      {JSON.stringify(selectedElement.data, null, 2)}
                    </Box>
                    {selectedElement.type === 'node' && onNavigateToIDE && (
                      <Button
                        size="small"
                        startIcon={<OpenInNew />}
                        onClick={() =>
                          onNavigateToIDE({
                            repo: (selectedElement.data as TopologyNodeData).repo_path || 'main',
                            file: 'scenarios/main.wire',
                          })
                        }
                        sx={{ mt: 1, textTransform: 'none', fontSize: 11 }}
                      >
                        Открыть исходники в IDE
                      </Button>
                    )}
                  </Card>
                </Panel>
              )}
            </ReactFlow>
          )}
        </Paper>

        {/* Add Node Dialog */}
        <Dialog open={openAddNodeDialog} onClose={() => setOpenAddNodeDialog(false)} maxWidth="sm" fullWidth>
          <DialogTitle sx={{ fontWeight: 700 }}>Добавить узел на граф топологии</DialogTitle>
          <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
            <TextField
              label="ID Узла"
              placeholder="app-billing"
              value={newNodeId}
              onChange={(e) => setNewNodeId(e.target.value)}
              fullWidth
              size="small"
              required
            />
            <TextField
              label="Отображаемое имя"
              placeholder="Сервис Биллинга"
              value={newNodeLabel}
              onChange={(e) => setNewNodeLabel(e.target.value)}
              fullWidth
              size="small"
              required
            />
            <TextField
              select
              label="Уровень узла (Level)"
              value={newNodeLevel}
              onChange={(e) => setNewNodeLevel(Number(e.target.value))}
              fullWidth
              size="small"
            >
              <MenuItem value={0}>L0 — Общая библиотека (uses_library)</MenuItem>
              <MenuItem value={1}>L1 — Микросервис / Приложение</MenuItem>
              <MenuItem value={2}>L2 — Группа / Подсистема (contains)</MenuItem>
              <MenuItem value={3}>L3 — Комплекс</MenuItem>
            </TextField>
            <TextField
              label="Git Репозиторий"
              placeholder="cbr/billing-service"
              value={newNodeRepo}
              onChange={(e) => setNewNodeRepo(e.target.value)}
              fullWidth
              size="small"
            />
          </DialogContent>
          <DialogActions sx={{ p: 2 }}>
            <Button onClick={() => setOpenAddNodeDialog(false)}>Отмена</Button>
            <Button onClick={handleAddNode} variant="contained" disabled={!newNodeId || !newNodeLabel}>
              Разместить на графе
            </Button>
          </DialogActions>
        </Dialog>
      </Box>
    </ErrorBoundary>
  );
}
