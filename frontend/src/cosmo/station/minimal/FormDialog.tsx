/**
 * FR-001: Reusable Form Dialog.
 */
import { Dialog, DialogTitle, DialogContent, DialogActions, Button, Box } from '@mui/material';
import type { ReactNode } from 'react';

interface FormDialogProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  onSubmit: () => void;
  submitLabel?: string;
  submitDisabled?: boolean;
  submitting?: boolean;
  maxWidth?: 'xs' | 'sm' | 'md';
}

export function FormDialog({ open, onClose, title, children, onSubmit, submitLabel = 'Создать', submitDisabled, submitting, maxWidth = 'sm' }: FormDialogProps) {
  return (
    <Dialog open={open} onClose={onClose} maxWidth={maxWidth} fullWidth>
      <DialogTitle sx={{ fontWeight: 700 }}>{title}</DialogTitle>
      <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
        {children}
      </DialogContent>
      <DialogActions sx={{ p: 2 }}>
        <Button onClick={onClose} disabled={submitting}>Отмена</Button>
        <Button variant="contained" onClick={onSubmit} disabled={submitDisabled || submitting} sx={{ textTransform: 'none', fontWeight: 600 }}>
          {submitting ? 'Сохранение...' : submitLabel}
        </Button>
      </DialogActions>
    </Dialog>
  );
}