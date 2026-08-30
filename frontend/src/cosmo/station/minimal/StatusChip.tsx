/**
 * FR-001: Status chip with unified color scheme.
 */
import { Chip, type ChipProps } from '@mui/material';

const statusMap: Record<string, { color: ChipProps['color']; label: string }> = {
  active:     { color: 'success', label: 'Active' },
  archived:   { color: 'default', label: 'Архивный' },
  planning:   { color: 'info',    label: 'Планирование' },
  success:    { color: 'success', label: 'Success' },
  failed:     { color: 'error',   label: 'Failed' },
  running:    { color: 'primary', label: 'Running' },
  pending:    { color: 'default', label: 'Pending' },
  deployed:   { color: 'success', label: 'Deployed' },
  validating: { color: 'warning', label: 'Validating' },
  draft:      { color: 'default', label: 'Draft' },
  aborted:    { color: 'warning', label: 'Aborted' },
  rolling:    { color: 'info',    label: 'Rolling' },
  deleted:    { color: 'error',   label: 'Deleted' },
};

interface StatusChipProps {
  status: string;
  label?: string;
  size?: 'small' | 'medium';
}

export function StatusChip({ status, label, size = 'small' }: StatusChipProps) {
  const meta = statusMap[status] || { color: 'default' as const, label: status };
  return (
    <Chip
      label={label ?? meta.label}
      size={size}
      color={meta.color}
      variant="outlined"
      sx={{ fontWeight: 600, fontSize: size === 'small' ? 10 : 12, height: size === 'small' ? 20 : 28 }}
    />
  );
}