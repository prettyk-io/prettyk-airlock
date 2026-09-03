/**
 * COS-020: Surface Switcher — переключатель Control Station ↔ Web IDE.
 *
 * Обе поверхности живут в одном SPA, переключатель в правом верхнем углу.
 * CSS-изоляция через class scoping: .cosmo-control-station vs .cosmo-ide-root.
 */
import { useState } from 'react';

type CosmoSurface = 'station' | 'ide';

export function SurfaceSwitcher({ surface, onChange }: { surface: CosmoSurface; onChange: (s: CosmoSurface) => void }) {
  return (
    <div className="cosmo-surface-switcher" data-testid="surface-switcher">
      <button
        data-testid="switch-to-station"
        className={surface === 'station' ? 'active' : ''}
        onClick={() => onChange('station')}
      >
        Control Station
      </button>
      <button
        data-testid="switch-to-ide"
        className={surface === 'ide' ? 'active' : ''}
        onClick={() => onChange('ide')}
      >
        Web IDE
      </button>
    </div>
  );
}