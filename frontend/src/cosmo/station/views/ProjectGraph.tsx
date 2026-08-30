/**
 * NX-FLASH-03: Project React Flow Graph — API-driven, no synthetic data.
 */
import { useEffect, useState, useCallback } from 'react';
import {
  ReactFlow, Background, Controls, MiniMap, Panel, Handle, Position,
  type Node, type Edge, type NodeProps,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {
  Box, Typography, Button, Chip, Paper, Alert, CircularProgress,
} from '@mui/material';
import { api } from '../api';
import { ErrorBoundary } from '../../shared/ErrorBoundary';
import { StatusChip } from '../minimal/StatusChip';

interface ProjectGraphProps {
  projectId: string;
  onBack: () => void;
}

function GraphNode({ data }: NodeProps) {
  const d = data as any;
  return (
    <Paper variant="outlined" sx={{ p: 1.5, borderRadius: 2, minWidth: 140, border: 2, borderColor: d.level === 0 ? '#A855F7' : '#3B82F6' }}>
      <Handle type="target" position={Position.Left} />
      <Typography variant="caption" sx={{ fontWeight: 700, fontSize: 11, display: 'block' }}>{d.label}</Typography>
      <Box sx={{ display: 'flex', gap: 0.5, mt: 0.5 }}>
        <Chip label={`L${d.level}`} size="small" sx={{ fontSize: 8, height: 16, bgcolor: d.level === 0 ? '#A855F7' : '#3B82F6', color: '#fff' }} />
        {d.status && <StatusChip status={d.status} />}
      </Box>
      <Handle type="source" position={Position.Right} />
    </Paper>
  );
}

const nodeTypes = { graphNode: GraphNode };

export function ProjectGraph({ projectId, onBack }: ProjectGraphProps) {
  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchGraph = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getProjectGraph(projectId);
      if (data) {
        setNodes(data.nodes.map((n: any) => ({
          id: n.id, type: 'graphNode',
          position: { x: n.x || 100, y: n.y || 100 },
          data: { label: n.label, level: n.level, status: n.status, appId: n.app_id },
        })));
        setEdges(data.edges.map((e: any) => ({
          id: e.id, source: e.from, target: e.to,
          type: 'smoothstep',
          animated: false,
          style: { stroke: e.relation === 'uses_library' ? '#A855F7' : '#3B82F6', strokeWidth: 2, strokeDasharray: e.relation === 'uses_library' ? '6 3' : undefined },
        })));
      }
    } catch (err: unknown) {
      setError((err as Error)?.message || 'Ошибка загрузки графа');
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => { fetchGraph(); }, [fetchGraph]);

  return (
    <ErrorBoundary viewName="Project Graph">
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, height: 'calc(100vh - 140px)' }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Box>
            <Typography variant="h5" sx={{ fontWeight: 700 }}>Граф зависимостей проекта</Typography>
            <Typography variant="body2" color="text.secondary">
              Nodes/edges from API · {nodes.length} nodes · {edges.length} edges
            </Typography>
          </Box>
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Button size="small" onClick={fetchGraph} disabled={loading} sx={{ textTransform: 'none' }}>Обновить</Button>
            <Button size="small" variant="outlined" onClick={onBack} sx={{ textTransform: 'none' }}>← Назад</Button>
          </Box>
        </Box>

        {error && <Alert severity="error">{error}</Alert>}

        {loading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', flex: 1 }}>
            <CircularProgress />
          </Box>
        ) : (
          <Box sx={{ flex: 1, borderRadius: 2, border: 1, borderColor: 'divider', overflow: 'hidden' }}>
            <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView>
              <Background />
              <Controls />
              <MiniMap nodeStrokeWidth={3} pannable zoomable />
              <Panel position="bottom-left">
                <Box sx={{ display: 'flex', gap: 1, p: 1, bgcolor: 'background.paper', borderRadius: 2, boxShadow: 2 }}>
                  <Chip label="depends_on" size="small" sx={{ bgcolor: '#3B82F6', color: '#fff' }} />
                  <Chip label="uses_library" size="small" variant="outlined" sx={{ borderColor: '#A855F7', color: '#A855F7' }} />
                </Box>
              </Panel>
            </ReactFlow>
          </Box>
        )}
      </Box>
    </ErrorBoundary>
  );
}