/**
 * COS-012: usePreference — REST-based preference persistence.
 *
 * Читает/пишет настройки через GET/PUT /api/v1/preferences.
 * НЕ использует localStorage для доменных данных.
 *
 * Использование:
 *   const [prefs, setPrefs] = usePreference();
 *   setPrefs('theme', 'dark');  // PUT на сервер
 *   setPrefs('domain', 'd-1');
 */
import { useState, useEffect, useCallback } from 'react';

export type ThemeMode = 'light' | 'dark';

export interface UserPreferences {
  theme: ThemeMode;
  domain: string;
  env: string;
  nav: string;
}

const DEFAULTS: UserPreferences = {
  theme: 'light',
  domain: 'all',
  env: 'stage',
  nav: 'domains',
};

let _cachedPrefs: UserPreferences | null = null;
let _fetchPromise: Promise<UserPreferences> | null = null;

async function fetchPreferences(apiBase: string): Promise<UserPreferences> {
  if (_cachedPrefs) return _cachedPrefs;
  if (_fetchPromise) return _fetchPromise;

  _fetchPromise = (async () => {
    try {
      const res = await fetch(`${apiBase}/api/v1/preferences`, {
        credentials: 'include',
      });
      if (res.ok) {
        _cachedPrefs = await res.json();
        return _cachedPrefs!;
      }
    } catch {
      /* fall through to defaults */
    }
    _cachedPrefs = { ...DEFAULTS };
    return _cachedPrefs!;
  })();

  return _fetchPromise;
}

async function savePreferences(
  prefs: UserPreferences,
  apiBase: string,
): Promise<UserPreferences> {
  try {
    const res = await fetch(`${apiBase}/api/v1/preferences`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(prefs),
    });
    if (res.ok) {
      const saved = await res.json();
      _cachedPrefs = { ...prefs, ...saved };
      return _cachedPrefs!;
    }
  } catch {
    /* offline — return local */
  }
  _cachedPrefs = prefs;
  return prefs;
}

export function usePreference<K extends keyof UserPreferences>(
  key: K,
  apiBase: string = '',
): [UserPreferences[K], (value: UserPreferences[K]) => void] {
  const [value, setValue] = useState<UserPreferences[K]>(DEFAULTS[key]);

  useEffect(() => {
    let cancelled = false;
    fetchPreferences(apiBase).then((prefs) => {
      if (!cancelled) setValue(prefs[key]);
    });
    return () => { cancelled = true; };
  }, [key, apiBase]);

  const setter = useCallback(
    (newVal: UserPreferences[K]) => {
      setValue(newVal);
      const updated = { ...(_cachedPrefs || DEFAULTS), [key]: newVal };
      savePreferences(updated, apiBase);
    },
    [key, apiBase],
  );

  return [value, setter];
}

/**
 * Batch update нескольких preferences за один PUT.
 */
export async function updatePreferences(
  patch: Partial<UserPreferences>,
  apiBase: string = '',
): Promise<UserPreferences> {
  _cachedPrefs = { ...(_cachedPrefs || DEFAULTS), ...patch };
  return savePreferences(_cachedPrefs!, apiBase);
}

/** Очистить кеш (для тестов). */
export function clearPrefsCache() {
  _cachedPrefs = null;
  _fetchPromise = null;
}