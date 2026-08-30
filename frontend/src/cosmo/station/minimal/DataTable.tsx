/**
 * FR-002: DataTable — MUI X Data Grid wrapper with Minimal UI aesthetic.
 *
 * Server-side pagination, sorting, filter support, column management,
 * density, row actions, deep links, loading/error/empty states.
 */
import { DataGrid, type GridColDef, type GridRowParams, type GridSortModel, type GridPaginationModel, type GridFilterModel, type GridValidRowModel } from '@mui/x-data-grid';
import { Box, LinearProgress, Typography } from '@mui/material';
import { EmptyTable } from './EmptyTable';
import { useRef } from 'react';

interface DataTableProps<T extends GridValidRowModel> {
  columns: GridColDef[];
  rows: T[];
  loading?: boolean;
  error?: string | null;
  pageSize?: number;
  rowCount?: number;
  paginationModel?: GridPaginationModel;
  onPaginationModelChange?: (model: GridPaginationModel) => void;
  sortModel?: GridSortModel;
  onSortModelChange?: (model: GridSortModel) => void;
  filterModel?: GridFilterModel;
  onFilterModelChange?: (model: GridFilterModel) => void;
  onRowClick?: (params: GridRowParams<T>) => void;
  getRowId?: (row: T) => string;
  density?: 'compact' | 'standard' | 'comfortable';
  emptyTitle?: string;
  emptyDescription?: string;
  height?: number | string;
  disableColumnMenu?: boolean;
}

export function DataTable<T extends GridValidRowModel>({
  columns, rows, loading, error,
  pageSize = 25,
  paginationModel, onPaginationModelChange,
  sortModel, onSortModelChange,
  filterModel, onFilterModelChange,
  onRowClick, getRowId,
  density = 'compact',
  emptyTitle = 'Нет данных',
  emptyDescription = 'Записи не найдены.',
  height = 560,
  disableColumnMenu = false,
}: DataTableProps<T>) {
  const idFn = getRowId || ((row: any) => row.id);

  if (error) {
    return (
      <Box sx={{ p: 4, textAlign: 'center' }}>
        <Typography color="error" variant="body2">Ошибка загрузки: {error}</Typography>
      </Box>
    );
  }

  return (
    <Box sx={{ width: '100%', height }}>
      <DataGrid
        columns={columns}
        rows={rows}
        getRowId={idFn}
        loading={loading}
        density={density}
        pagination
        paginationMode="server"
        paginationModel={paginationModel}
        onPaginationModelChange={onPaginationModelChange}
        pageSizeOptions={[10, 25, 50]}
        rowCount={rows.length}
        sortingMode="server"
        sortModel={sortModel}
        onSortModelChange={onSortModelChange}
        filterMode="server"
        filterModel={filterModel}
        onFilterModelChange={onFilterModelChange}
        onRowClick={onRowClick}
        disableColumnMenu={disableColumnMenu}
        disableRowSelectionOnClick
        slots={{
          loadingOverlay: () => <LinearProgress sx={{ width: '100%' }} />,
          noRowsOverlay: () => (
            <EmptyTable title={emptyTitle} description={emptyDescription} />
          ),
        }}
        sx={{
          border: '1px solid',
          borderColor: 'divider',
          borderRadius: 2,
          '& .MuiDataGrid-columnHeaders': {
            bgcolor: 'action.hover',
            fontWeight: 600,
            fontSize: 12,
            textTransform: 'uppercase',
            letterSpacing: 0.5,
          },
          '& .MuiDataGrid-row': {
            cursor: onRowClick ? 'pointer' : 'default',
          },
          '& .MuiDataGrid-cell': {
            fontSize: 12,
            borderColor: 'divider',
          },
          '& .MuiDataGrid-footerContainer': {
            borderTop: '1px solid',
            borderColor: 'divider',
            minHeight: 40,
          },
        }}
      />
    </Box>
  );
}