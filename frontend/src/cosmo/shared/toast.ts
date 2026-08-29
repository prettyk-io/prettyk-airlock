/**
 * COS-047: Lightweight Toast Notification system for API feedback.
 */
import { useState, useEffect } from 'react';

export type ToastSeverity = 'success' | 'error' | 'warning' | 'info';

export interface ToastMessage {
  id: string;
  message: string;
  severity: ToastSeverity;
}

type ToastListener = (toasts: ToastMessage[]) => void;

let _toasts: ToastMessage[] = [];
const _listeners = new Set<ToastListener>();

function notify() {
  _listeners.forEach((listener) => listener([..._toasts]));
}

export const toast = {
  show(message: string, severity: ToastSeverity = 'info') {
    const id = `toast-${Date.now()}-${Math.random().toString(36).substring(2, 6)}`;
    const newToast: ToastMessage = { id, message, severity };
    _toasts = [..._toasts, newToast];
    notify();

    // Auto dismiss after 4 seconds
    setTimeout(() => {
      toast.dismiss(id);
    }, 4000);
  },

  success(message: string) {
    toast.show(message, 'success');
  },

  error(message: string) {
    toast.show(message, 'error');
  },

  warning(message: string) {
    toast.show(message, 'warning');
  },

  info(message: string) {
    toast.show(message, 'info');
  },

  dismiss(id: string) {
    _toasts = _toasts.filter((t) => t.id !== id);
    notify();
  },
};

export function useToastMessages(): ToastMessage[] {
  const [toasts, setToasts] = useState<ToastMessage[]>([..._toasts]);

  useEffect(() => {
    const listener: ToastListener = (updated) => setToasts(updated);
    _listeners.add(listener);
    return () => {
      _listeners.delete(listener);
    };
  }, []);

  return toasts;
}
