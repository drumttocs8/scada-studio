import React from 'react';
import { Box, Typography, Grid, Card, CardContent, CardActions, Button, Chip, Stack } from '@mui/material';
import DevicesIcon from '@mui/icons-material/Devices';
import ListAltIcon from '@mui/icons-material/ListAlt';
import StorageIcon from '@mui/icons-material/Storage';
import { useQuery } from '@tanstack/react-query';
import { configApi } from '../services/api';
import { useAppStore } from '../store';
import FileUpload from '../components/FileUpload';
import ConnectionStatus from '../components/ConnectionStatus';

export default function Dashboard() {
  const { setConfigs } = useAppStore();
  const { data: configs, isLoading, refetch } = useQuery({
    queryKey: ['configs'],
    queryFn: async () => {
      const resp = await configApi.list();
      setConfigs(resp.data);
      return resp.data;
    },
  });

  return (
    <Box>
      <Typography variant="h4" gutterBottom sx={{ fontWeight: 700 }}>Dashboard</Typography>
      <ConnectionStatus />

      <Grid container spacing={3} sx={{ mt: 1 }}>
        <Grid item xs={12} md={4}>
          <Card sx={{ bgcolor: '#1a3a5c' }}>
            <CardContent>
              <Stack direction="row" spacing={1} alignItems="center">
                <StorageIcon color="primary" />
                <Typography variant="h6">Configs</Typography>
              </Stack>
              <Typography variant="h3" sx={{ mt: 1 }}>{configs?.length || 0}</Typography>
              <Typography variant="body2" color="text.secondary">Uploaded RTAC XML files</Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={4}>
          <Card sx={{ bgcolor: '#1a3a5c' }}>
            <CardContent>
              <Stack direction="row" spacing={1} alignItems="center">
                <DevicesIcon color="secondary" />
                <Typography variant="h6">Devices</Typography>
              </Stack>
              <Typography variant="h3" sx={{ mt: 1 }}>
                {configs?.reduce((sum: number, c: any) => sum + (c.devices || 0), 0) || 0}
              </Typography>
              <Typography variant="body2" color="text.secondary">Server devices parsed</Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={4}>
          <Card sx={{ bgcolor: '#1a3a5c' }}>
            <CardContent>
              <Stack direction="row" spacing={1} alignItems="center">
                <ListAltIcon sx={{ color: '#ffb74d' }} />
                <Typography variant="h6">Points</Typography>
              </Stack>
              <Typography variant="h3" sx={{ mt: 1 }}>
                {configs?.reduce((sum: number, c: any) => sum + (c.points || 0), 0) || 0}
              </Typography>
              <Typography variant="body2" color="text.secondary">Total points extracted</Typography>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      <Box sx={{ mt: 4 }}>
        <Typography variant="h5" gutterBottom>Upload RTAC Configuration</Typography>
        <FileUpload onUploadComplete={() => refetch()} />
      </Box>

      {configs && configs.length > 0 && (
        <Box sx={{ mt: 4 }}>
          <Typography variant="h5" gutterBottom>Recent Configurations</Typography>
          <Grid container spacing={2}>
            {configs.map((config: any) => (
              <Grid item xs={12} md={6} key={config.id}>
                <Card sx={{ bgcolor: '#132f4c' }}>
                  <CardContent>
                    <Typography variant="h6">{config.filename}</Typography>
                    <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
                      <Chip label={`${config.devices} devices`} size="small" color="primary" variant="outlined" />
                      <Chip label={`${config.points} points`} size="small" color="secondary" variant="outlined" />
                    </Stack>
                    <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
                      Uploaded: {new Date(config.uploadedAt).toLocaleString()}
                    </Typography>
                  </CardContent>
                  <CardActions>
                    <Button size="small" href={`/editor?config=${config.id}`}>View / Edit</Button>
                    <Button size="small" color="error" onClick={async () => {
                      await configApi.remove(config.id);
                      refetch();
                    }}>Delete</Button>
                  </CardActions>
                </Card>
              </Grid>
            ))}
          </Grid>
        </Box>
      )}
    </Box>
  );
}
