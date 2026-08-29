/**
 * COS-020 / COS-053: CosmoThemeProvider — MUI Theme + CSS variable bridge.
 *
 * Meta Light как дефолт для Control Station. Meta Dark переключается.
 * CSS-переменные --cosmo-* маппятся в MUI theme tokens и синхронизируются с DOM.
 *
 * COS-012 / COS-053: Тема сохраняется через REST /api/v1/preferences,
 * НЕ через localStorage.
 */
import { createTheme, ThemeProvider } from '@mui/material';
import { useMemo, createContext, useContext, useEffect, type ReactNode } from 'react';
import type { ThemeMode } from '../shared/usePreference';
import { usePreference } from '../shared/usePreference';

export interface CosmoThemeContextValue {
  mode: ThemeMode;
  toggleMode: () => void;
  setMode: (mode: ThemeMode) => void;
}

const CosmoThemeContext = createContext<CosmoThemeContextValue>({
  mode: 'light',
  toggleMode: () => {},
  setMode: () => {},
});

export function useCosmoTheme(): CosmoThemeContextValue {
  return useContext(CosmoThemeContext);
}

export function buildMuiTheme(mode: ThemeMode) {
  const isDark = mode === 'dark';

  return createTheme({
    palette: {
      mode,
      primary: {
        main: '#0EA5E9',
        light: '#38BDF8',
        dark: '#0284C7',
        contrastText: '#FFFFFF',
      },
      secondary: {
        main: '#7C3AED',
        light: '#A78BFA',
        dark: '#5B21B6',
      },
      success: {
        main: '#10B981',
        light: '#34D399',
        dark: '#059669',
      },
      warning: {
        main: '#F59E0B',
        light: '#FBBF24',
        dark: '#D97706',
      },
      error: {
        main: '#EF4444',
        light: '#F87171',
        dark: '#DC2626',
      },
      background: {
        default: isDark ? '#0F172A' : '#FFFFFF',
        paper: isDark ? '#1E293B' : '#F8FAFC',
      },
      text: {
        primary: isDark ? '#F1F5F9' : '#0F172A',
        secondary: isDark ? '#94A3B8' : '#475569',
      },
      divider: isDark ? '#334155' : '#E2E8F0',
      action: {
        hover: isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.04)',
        selected: isDark ? 'rgba(14, 165, 233, 0.15)' : 'rgba(14, 165, 233, 0.08)',
        disabledBackground: isDark ? '#334155' : '#E2E8F0',
      },
    },
    typography: {
      fontFamily: '"Golos UI", "Inter", system-ui, sans-serif',
      fontSize: 13,
    },
    shape: { borderRadius: 8 },
    components: {
      MuiButton: {
        styleOverrides: {
          root: { textTransform: 'none', fontWeight: 600, borderRadius: 8 },
        },
      },
      MuiPaper: {
        styleOverrides: {
          root: { backgroundImage: 'none' },
        },
      },
      MuiChip: {
        styleOverrides: {
          root: { fontWeight: 600 },
        },
      },
    },
  });
}

export function CosmoThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = usePreference('theme');
  const toggleMode = () => setMode(mode === 'light' ? 'dark' : 'light');

  const theme = useMemo(() => buildMuiTheme(mode), [mode]);

  useEffect(() => {
    if (typeof document !== 'undefined') {
      document.documentElement.setAttribute('data-theme', mode);
      if (mode === 'dark') {
        document.documentElement.classList.add('dark');
      } else {
        document.documentElement.classList.remove('dark');
      }
    }
  }, [mode]);

  return (
    <CosmoThemeContext.Provider value={{ mode, toggleMode, setMode }}>
      <ThemeProvider theme={theme}>
        {/* Scoped theme container */}
        {children}
      </ThemeProvider>
    </CosmoThemeContext.Provider>
  );
}
