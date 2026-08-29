/**
 * COS-099: Global Keyboard Navigation & Hotkey Hook.
 *
 * Vim/Gmail-style navigation sequences (two-key combos):
 *   g o → Overview, g a → Applications, g t → Topology,
 *   g r → Runs, g g → Gates, g e → Evidence, g l → Releases,
 *   g c → Catalog, g u → Audit
 *
 * Quick actions:
 *   n r → New Run modal
 *   ? (Shift+/) → Help overlay
 *   Escape → close all modals/drawers/overlays
 *
 * Ignored when focus is inside input/textarea or Monaco editor.
 */
import { useEffect, useRef } from 'react';

type HotkeyAction = (e: KeyboardEvent) => void;

interface HotkeyMap {
  [sequence: string]: HotkeyAction;
}

/**
 * Regex that matches text input targets where hotkeys should be suppressed.
 */
const INPUT_RE = /^(input|textarea|select)$/i;

function isEditableTarget(el: Element | null): boolean {
  if (!el) return false;
  const tag = el.tagName;
  if (INPUT_RE.test(tag)) return true;
  if ((el as HTMLElement).isContentEditable) return true;
  // Monaco editor detection
  if (el.closest('.monaco-editor') || el.closest('[data-keybinding-context]')) return true;
  return false;
}

export function useHotkeys(navigate: (view: string) => void, openNewRun: () => void, closeAll: () => void) {
  const seqRef = useRef('');

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Ignore if focus is in a text input or Monaco
      const active = document.activeElement;
      if (isEditableTarget(active)) return;

      const key = e.key;

      // ── Escape: close all modals ──
      if (key === 'Escape') {
        e.preventDefault();
        closeAll();
        seqRef.current = '';
        return;
      }

      // ── ? (Shift+/ = '?') — help overlay ──
      if (key === '?') {
        e.preventDefault();
        seqRef.current = '';
        navigate('help');
        return;
      }

      // ── Two-key sequences ──
      // Ignore modifier keys alone
      if (['Control', 'Alt', 'Shift', 'Meta', 'CapsLock', 'Tab'].includes(key)) {
        return;
      }

      // Append to sequence
      seqRef.current += key.toLowerCase();

      // Match known sequences
      const seq = seqRef.current;

      switch (seq) {
        case 'go':
          e.preventDefault();
          navigate('domains');
          seqRef.current = '';
          break;
        case 'ga':
          e.preventDefault();
          navigate('applications');
          seqRef.current = '';
          break;
        case 'gt':
          e.preventDefault();
          navigate('topology');
          seqRef.current = '';
          break;
        case 'gr':
          e.preventDefault();
          navigate('runs');
          seqRef.current = '';
          break;
        case 'gg':
          e.preventDefault();
          navigate('gates');
          seqRef.current = '';
          break;
        case 'ge':
          e.preventDefault();
          navigate('evidence');
          seqRef.current = '';
          break;
        case 'gl':
          e.preventDefault();
          navigate('releases');
          seqRef.current = '';
          break;
        case 'gc':
          e.preventDefault();
          navigate('catalog');
          seqRef.current = '';
          break;
        case 'gu':
          e.preventDefault();
          navigate('audit');
          seqRef.current = '';
          break;
        case 'nr':
          e.preventDefault();
          openNewRun();
          seqRef.current = '';
          break;
        default:
          // If no match yet, keep accumulating up to 2 chars
          if (seq.length >= 2) {
            // No match after 2 chars, reset
            seqRef.current = key.toLowerCase();
          }
          break;
      }
    };

    const handleBlur = () => {
      seqRef.current = '';
    };

    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('blur', handleBlur);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('blur', handleBlur);
    };
  }, [navigate, openNewRun, closeAll]);
}