/**
 * Cosmoport 2.0 — App root.
 *
 * COS-020: Surface switcher (Control Station ↔ Web IDE).
 * COS-021: Control Station Shell (MUI + Meta Light).
 * COS-023: Web IDE Shell (Tailwind + Monaco + xterm).
 * COS-024: Deep-Linking — сквозная навигация через URL-параметры.
 */
import { CosmoThemeProvider } from './cosmo/theme';
import { SurfaceSwitcher } from './cosmo/shared/SurfaceSwitcher';
import { useDeepLink } from './cosmo/shared/DeepLinker';
import { ControlStationShell } from './cosmo/station/ControlStationShell';
import { WebIDEShell } from './cosmo/ide/WebIDEShell';
import './styles/global.css';
import './styles/control-station.css';
import './styles/web-ide.css';

export function App() {
  const { state, setSurface, setIDEContext, setStationContext } = useDeepLink();

  return (
    <CosmoThemeProvider>
      <SurfaceSwitcher surface={state.surface} onChange={setSurface} />
      {state.surface === 'station' ? (
        <ControlStationShell
          view={state.station.view}
          runId={state.station.run_id}
          onNavigateToIDE={setIDEContext}
        />
      ) : (
        <WebIDEShell
          repo={state.ide.repo}
          file={state.ide.file}
          line={state.ide.line}
          onNavigateToStation={setStationContext}
        />
      )}
    </CosmoThemeProvider>
  );
}