import React from 'react';
import { Box, Paper, Typography, Chip, Stack } from '@mui/material';

interface DiffViewerProps {
  diff: {
    label1: string;
    label2: string;
    totalChanges: number;
    changes: Array<{ type: 'added' | 'removed' | 'unchanged'; line: string; lineNumber: number }>;
  };
}

export default function DiffViewer({ diff }: DiffViewerProps) {
  const colors = { added: '#1b5e20', removed: '#b71c1c', unchanged: 'transparent' };
  const prefixes = { added: '+', removed: '-', unchanged: ' ' };

  return (
    <Paper sx={{ mt: 3, p: 2 }}>
      <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2 }}>
        <Typography variant="h6">Diff Result</Typography>
        <Chip label={`${diff.totalChanges} changes`} size="small" color={diff.totalChanges > 0 ? 'warning' : 'success'} />
      </Stack>
      <Typography variant="caption" color="text.secondary">
        {diff.label1} vs {diff.label2}
      </Typography>
      <Box sx={{ mt: 1, maxHeight: 500, overflow: 'auto', fontFamily: 'monospace', fontSize: 12 }}>
        {diff.changes.map((change, i) => (
          <Box
            key={i}
            sx={{
              bgcolor: colors[change.type], px: 1, py: 0.2, borderLeft: change.type !== 'unchanged' ? '3px solid' : 'none',
              borderColor: change.type === 'added' ? '#4caf50' : change.type === 'removed' ? '#f44336' : 'transparent'
            }}
          >
            <span style={{ color: '#888', marginRight: 8, userSelect: 'none' }}>{String(change.lineNumber).padStart(4)}</span>
            <span style={{ color: '#888', marginRight: 4 }}>{prefixes[change.type]}</span>
            {change.line}
          </Box>
        ))}
      </Box>
    </Paper>
  );
}
