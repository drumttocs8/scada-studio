import React, { useState, useEffect } from 'react';
import { Box, Typography, Grid, Paper, Tabs, Tab, Button, CircularProgress } from '@mui/material';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { configApi } from '../services/api';
import ConfigEditor from '../components/ConfigEditor';
import PointsListGenerator from '../components/PointsListGenerator';

export default function Editor() {
  const [searchParams] = useSearchParams();
  const configId = searchParams.get('config');
  const [tab, setTab] = useState(0);

  const { data: config, isLoading } = useQuery({
    queryKey: ['config', configId],
    queryFn: () => configId ? configApi.get(configId).then((r) => r.data) : null,
    enabled: !!configId,
  });

  const { data: xml } = useQuery({
    queryKey: ['config-xml', configId],
    queryFn: () => configId ? configApi.getXml(configId).then((r) => r.data) : null,
    enabled: !!configId,
  });

  if (!configId) {
    return (
      <Box>
        <Typography variant="h4" gutterBottom sx={{ fontWeight: 700 }}>XML Editor</Typography>
        <Typography color="text.secondary">Select a configuration from the Dashboard to edit, or upload a new file.</Typography>
      </Box>
    );
  }

  if (isLoading) return <CircularProgress />;

  return (
    <Box>
      <Typography variant="h4" gutterBottom sx={{ fontWeight: 700 }}>
        {config?.filename || 'Editor'}
      </Typography>

      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        <Tab label="XML Source" />
        <Tab label="Devices" />
        <Tab label="Points" />
        <Tab label="Points List" />
      </Tabs>

      {tab === 0 && (
        <ConfigEditor xml={typeof xml === 'string' ? xml : ''} filename={config?.filename || 'config.xml'} />
      )}

      {tab === 1 && (
        <Paper sx={{ p: 2 }}>
          <Typography variant="h6" gutterBottom>Server Devices ({config?.devices?.length || 0})</Typography>
          {config?.devices?.map((d: any, i: number) => (
            <Paper key={i} sx={{ p: 2, mb: 1, bgcolor: '#0d2137' }}>
              <Typography><strong>{d.deviceName}</strong></Typography>
              <Typography variant="body2" color="text.secondary">Map: {d.mapName} | File: {d.sourceFile}</Typography>
            </Paper>
          ))}
        </Paper>
      )}

      {tab === 2 && (
        <Paper sx={{ p: 2 }}>
          <Typography variant="h6" gutterBottom>Points ({config?.points?.length || 0})</Typography>
          <Box sx={{ maxHeight: 500, overflow: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #555' }}>
                  <th style={{ textAlign: 'left', padding: '8px' }}>Name</th>
                  <th style={{ textAlign: 'left', padding: '8px' }}>Address</th>
                  <th style={{ textAlign: 'left', padding: '8px' }}>Type</th>
                  <th style={{ textAlign: 'left', padding: '8px' }}>Map</th>
                  <th style={{ textAlign: 'left', padding: '8px' }}>File</th>
                </tr>
              </thead>
              <tbody>
                {config?.points?.map((p: any, i: number) => (
                  <tr key={i} style={{ borderBottom: '1px solid #333' }}>
                    <td style={{ padding: '6px 8px' }}>{p.name}</td>
                    <td style={{ padding: '6px 8px' }}>{p.address}</td>
                    <td style={{ padding: '6px 8px' }}>{p.type}</td>
                    <td style={{ padding: '6px 8px' }}>{p.mapName}</td>
                    <td style={{ padding: '6px 8px' }}>{p.sourceFile}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Box>
        </Paper>
      )}

      {tab === 3 && configId && (
        <PointsListGenerator configId={configId} />
      )}
    </Box>
  );
}
