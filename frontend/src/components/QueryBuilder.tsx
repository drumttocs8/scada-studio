import React from 'react';
import { Box, Typography } from '@mui/material';

// QueryBuilder is integrated directly into the Query page.
// This component is kept for potential reuse as a standalone widget.
export default function QueryBuilder() {
  return (
    <Box>
      <Typography variant="body2" color="text.secondary">
        Use the Query page for RAG search and CIM topology queries.
      </Typography>
    </Box>
  );
}
