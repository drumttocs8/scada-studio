import React from 'react';
import { Stack, Chip } from '@mui/material';
import { useQuery } from '@tanstack/react-query';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import axios from 'axios';

export default function ConnectionStatus() {
  const apiBase = import.meta.env.VITE_API_URL || '/api';
  const { data: backendOk } = useQuery({
    queryKey: ['health-backend'],
    queryFn: () => axios.get(`${apiBase.replace('/api', '')}/health`).then(() => true).catch(() => false),
    refetchInterval: 30000,
  });

  return (
    <Stack direction="row" spacing={1} sx={{ mb: 2 }}>
      <Chip
        label="Backend"
        size="small"
        color={backendOk ? 'success' : 'error'}
        icon={backendOk ? <CheckCircleIcon /> : <ErrorIcon />}
        variant="outlined"
      />
    </Stack>
  );
}
