import React, { useState } from 'react';
import { Box, Button, Paper, Typography, CircularProgress, Alert, Chip, Stack } from '@mui/material';
import ListAltIcon from '@mui/icons-material/ListAlt';
import DownloadIcon from '@mui/icons-material/Download';
import { configApi } from '../services/api';

interface PointsListGeneratorProps {
  configId: string;
}

export default function PointsListGenerator({ configId }: PointsListGeneratorProps) {
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleGenerate = async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await configApi.generatePoints(configId);
      setResult(resp.data);
    } catch (err: any) {
      setError(err.response?.data?.error || err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleDownload = () => {
    if (!result) return;
    const blob = new Blob([JSON.stringify(result.points, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${result.filename || 'points'}_points.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleDownloadCsv = () => {
    if (!result?.points?.length) return;
    const headers = Object.keys(result.points[0]);
    const csv = [headers.join(','), ...result.points.map((p: any) => headers.map((h) => `"${(p[h] || '').toString().replace(/"/g, '""')}"`).join(','))].join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${result.filename || 'points'}_points.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Paper sx={{ p: 3 }}>
      <Typography variant="h6" gutterBottom>
        <ListAltIcon sx={{ mr: 1, verticalAlign: 'middle' }} />
        Points List Generator
      </Typography>
      <Typography variant="body2" color="text.secondary" gutterBottom>
        Generate a structured points list from the parsed RTAC configuration.
      </Typography>

      <Button variant="contained" onClick={handleGenerate} disabled={loading} sx={{ mt: 1 }}>
        {loading ? <CircularProgress size={18} /> : 'Generate Points List'}
      </Button>

      {error && <Alert severity="error" sx={{ mt: 2 }}>{error}</Alert>}

      {result && (
        <Box sx={{ mt: 2 }}>
          <Stack direction="row" spacing={1} sx={{ mb: 2 }}>
            <Chip label={`${result.totalPoints} points`} color="primary" />
            <Button size="small" startIcon={<DownloadIcon />} onClick={handleDownload}>JSON</Button>
            <Button size="small" startIcon={<DownloadIcon />} onClick={handleDownloadCsv}>CSV</Button>
          </Stack>

          <Box sx={{ maxHeight: 400, overflow: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: '2px solid #555' }}>
                  {result.points.length > 0 && Object.keys(result.points[0]).map((key: string) => (
                    <th key={key} style={{ textAlign: 'left', padding: '6px 8px', whiteSpace: 'nowrap' }}>{key}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.points.slice(0, 200).map((point: any, i: number) => (
                  <tr key={i} style={{ borderBottom: '1px solid #333' }}>
                    {Object.values(point).map((val: any, j: number) => (
                      <td key={j} style={{ padding: '4px 8px' }}>{String(val)}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            {result.points.length > 200 && (
              <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
                Showing 200 of {result.totalPoints} points. Download for full list.
              </Typography>
            )}
          </Box>
        </Box>
      )}
    </Paper>
  );
}
