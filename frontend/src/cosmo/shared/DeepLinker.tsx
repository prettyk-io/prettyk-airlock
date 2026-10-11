/**
 * COS-024: DeepLinker — сквозная навигация через URL-параметры.
 *
 * Три сценария:
 *   1. Gate Inspector → строка кода
 *      ?surface=ide&repo=payments/api&file=scenarios/auth.wire&line=7
 *   2. Commit & Run → Live DAG
 *      ?surface=station&view=run&run_id=1043
 *   3. LC Config → редактор
 *      ?surface=ide&repo=core/config&file=.cosmo/pipeline.yaml
 *
 * Хук useDeepLink() читает URL при первом рендере и синхронизирует
 * URL при переключении surface через SurfaceSwitcher.
 */
import { useState, useEffect, useCallback } from 'react';

export type CosmoSurface = 'station' | 'ide';

export interface IDEContext {
  repo?: string;
  file?: string;
  line?: number;
  /** COS-179 / FR-004: immutable snapshot — commit SHA (ref-режим чтения). */
  commit?: string;
}

export interface StationContext {
  view?: string;
  run_id?: string;
}

export interface DeepLinkState {
  surface: CosmoSurface;
  ide: IDEContext;
  station: StationContext;
}

/** Разобрать query-строку в типизированные параметры. */
export function parseParams(): DeepLinkState {
  const p = new URLSearchParams(window.location.search);

  const surface = (p.get('surface') || 'station') as CosmoSurface;
  const repo = p.get('repo') || undefined;
  const file = p.get('file') || undefined;
  const rawLine = p.get('line');
  const line = rawLine ? parseInt(rawLine, 10) || undefined : undefined;
  const commit = p.get('commit') || undefined;
  const view = p.get('view') || undefined;
  const run_id = p.get('run_id') || undefined;

  return {
    surface: surface === 'ide' ? 'ide' : 'station',
    ide: { repo, file, line, commit },
    station: { view, run_id },
  };
}

/** Синхронизировать состояние в URL, НЕ перезагружая страницу. */
function pushUrl(state: DeepLinkState) {
  const p = new URLSearchParams();
  p.set('surface', state.surface);
  if (state.ide.repo) p.set('repo', state.ide.repo);
  if (state.ide.file) p.set('file', state.ide.file);
  if (state.ide.line) p.set('line', String(state.ide.line));
  if (state.ide.commit) p.set('commit', state.ide.commit);
  if (state.station.view) p.set('view', state.station.view);
  if (state.station.run_id) p.set('run_id', state.station.run_id);

  const qs = p.toString();
  const url = qs ? `${window.location.pathname}?${qs}` : window.location.pathname;
  window.history.replaceState(null, '', url);
}

/** Ссылка для deep-link навигации. */
export function buildLink(params: Partial<DeepLinkState> & { surface: CosmoSurface }): string {
  const p = new URLSearchParams();
  p.set('surface', params.surface);
  if (params.ide?.repo) p.set('repo', params.ide.repo);
  if (params.ide?.file) p.set('file', params.ide.file);
  if (params.ide?.line) p.set('line', String(params.ide.line));
  if (params.ide?.commit) p.set('commit', params.ide.commit);
  if (params.station?.view) p.set('view', params.station.view);
  if (params.station?.run_id) p.set('run_id', params.station.run_id);
  return `${window.location.pathname}?${p.toString()}`;
}

/**
 * COS-024: хук deep-linking.
 *
 * Читает URL при mount, возвращает текущее состояние поверхности
 * и функцию переключения, которая обновляет URL.
 */
export function useDeepLink(): {
  state: DeepLinkState;
  setSurface: (s: CosmoSurface) => void;
  setIDEContext: (ctx: Partial<IDEContext>) => void;
  setStationContext: (ctx: Partial<StationContext>) => void;
} {
  const [state, setState] = useState<DeepLinkState>(parseParams);

  const setSurface = useCallback((surface: CosmoSurface) => {
    setState((prev) => {
      const next = { ...prev, surface };
      pushUrl(next);
      return next;
    });
  }, []);

  const setIDEContext = useCallback((ctx: Partial<IDEContext>) => {
    setState((prev) => {
      const next: DeepLinkState = { ...prev, surface: 'ide', ide: { ...prev.ide, ...ctx } };
      pushUrl(next);
      return next;
    });
  }, []);

  const setStationContext = useCallback((ctx: Partial<StationContext>) => {
    setState((prev) => {
      const next: DeepLinkState = { ...prev, surface: 'station', station: { ...prev.station, ...ctx } };
      pushUrl(next);
      return next;
    });
  }, []);

  return { state, setSurface, setIDEContext, setStationContext };
}