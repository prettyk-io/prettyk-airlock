/**
 * COS-099: Keyboard Shortcuts Help Sheet Overlay.
 *
 * Displays a modal cheat sheet of all available hotkey sequences.
 * Triggered by '?' (Shift+/) or navigating to 'help' view.
 */
import {
  Box, Typography, Dialog, DialogTitle, DialogContent,
  Table, TableBody, TableCell, TableRow, Paper, Chip, Divider,
} from '@mui/material';
import { Keyboard } from '@mui/icons-material';

interface HotkeyOverlayProps {
  open: boolean;
  onClose: () => void;
}

const NAVIGATION_HOTKEYS = [
  { keys: 'g o', action: 'Обзор / Домены' },
  { keys: 'g a', action: 'Приложения' },
  { keys: 'g t', action: 'Топология (Граф)' },
  { keys: 'g r', action: 'Прогоны (Runs)' },
  { keys: 'g g', action: 'Гейты (Security Gates)' },
  { keys: 'g e', action: 'Доказательства (Evidence)' },
  { keys: 'g l', action: 'Релизы (Releases)' },
  { keys: 'g c', action: 'Каталог кирпичей' },
  { keys: 'g u', action: 'Аудит (Audit Log)' },
];

const ACTION_HOTKEYS = [
  { keys: 'n r', action: 'Новый прогон (New Run)' },
  { keys: '⌘K / Ctrl+K', action: 'Глобальный поиск' },
  { keys: '⌘S / Ctrl+S', action: 'Сохранить файл (IDE)' },
  { keys: '⌘D / Ctrl+D', action: 'Переключить Diff View (IDE)' },
  { keys: 'Escape', action: 'Закрыть все модальные окна' },
  { keys: '?', action: 'Показать справку по клавишам' },
];

export function HotkeyOverlay({ open, onClose }: HotkeyOverlayProps) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="sm"
      fullWidth
      slotProps={{
        paper: {
          sx: {
            borderRadius: 3,
            bgcolor: 'background.paper',
            boxShadow: '0 20px 40px rgba(0,0,0,0.3)',
          },
        },
      }}
    >
      <DialogTitle
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 1,
          fontWeight: 700,
        }}
      >
        <Keyboard sx={{ color: 'primary.main' }} />
        Справка по горячим клавишам (Keyboard Shortcuts)
      </DialogTitle>
      <DialogContent>
        {/* Navigation: Vim/Gmail style */}
        <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>
          Навигация (Vim/Gmail style)
        </Typography>
        <Paper variant="outlined" sx={{ borderRadius: 2, overflow: 'hidden', mb: 2 }}>
          <Table size="small">
            <TableBody>
              {NAVIGATION_HOTKEYS.map((hk) => (
                <TableRow key={hk.keys} hover>
                  <TableCell sx={{ width: 120, whiteSpace: 'nowrap' }}>
                    <Chip
                      label={hk.keys}
                      size="small"
                      color="primary"
                      variant="outlined"
                      sx={{
                        fontFamily: 'monospace',
                        fontWeight: 700,
                        fontSize: 12,
                        letterSpacing: 1,
                      }}
                    />
                  </TableCell>
                  <TableCell sx={{ fontSize: 13, fontWeight: 500 }}>
                    {hk.action}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Paper>

        <Divider sx={{ my: 2 }} />

        {/* Actions */}
        <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>
          Быстрые действия
        </Typography>
        <Paper variant="outlined" sx={{ borderRadius: 2, overflow: 'hidden', mb: 2 }}>
          <Table size="small">
            <TableBody>
              {ACTION_HOTKEYS.map((hk) => (
                <TableRow key={hk.keys} hover>
                  <TableCell sx={{ width: 150, whiteSpace: 'nowrap' }}>
                    <Chip
                      label={hk.keys}
                      size="small"
                      color="warning"
                      variant="outlined"
                      sx={{
                        fontFamily: 'monospace',
                        fontWeight: 700,
                        fontSize: 12,
                      }}
                    />
                  </TableCell>
                  <TableCell sx={{ fontSize: 13, fontWeight: 500 }}>
                    {hk.action}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Paper>

        <Typography variant="caption" color="text.secondary">
          Клавиатурные сокращения не срабатывают, если фокус находится в текстовом поле (input, textarea) или редакторе Monaco.
          Нажмите <Chip label="Escape" size="small" sx={{ fontFamily: 'monospace', fontWeight: 700, fontSize: 11 }} /> для сброса текущей последовательности.
        </Typography>
      </DialogContent>
    </Dialog>
  );
}