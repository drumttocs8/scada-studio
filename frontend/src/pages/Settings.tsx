import React, { useState, useEffect } from 'react';
import { Box, Typography, TextField, Button, Paper, Alert, Stack, Chip, CircularProgress } from '@mui/material';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import { settingsApi } from '../services/api';

export default function Settings() {
  const [url, setUrl] = useState('');
  const [token, setToken] = useState('');
  const [username, setUsername] = useState('');
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    settingsApi.getGitea().then((resp) => {
      setUrl(resp.data.url || '');
      setUsername(resp.data.username || '');
    }).catch(() => { });
  }, []);

  const handleSave = async () => {
    setStatus('saving');
    setError(null);
    try {
      await settingsApi.updateGitea({ url, token: token || undefined, username });
      setStatus('saved');
      setToken('');
    } catch (err: any) {
      setStatus('error');
      setError(err.response?.data?.error || err.message);
    }
  };

  return (
    <Box>
      <Typography variant="h4" gutterBottom sx={{ fontWeight: 700 }}>Settings</Typography>

      <Paper sx={{ p: 3, mt: 2, maxWidth: 600 }}>
        <Typography variant="h6" gutterBottom>Git Server Connection</Typography>
        <Typography variant="body2" color="text.secondary" gutterBottom>
          Connect to Gitea or any compatible Git server for version control.
        </Typography>

        <Stack spacing={2} sx={{ mt: 2 }}>
          <TextField fullWidth label="Server URL" placeholder="http://gitea:3000" value={url} onChange={(e) => setUrl(e.target.value)} />
          <TextField fullWidth label="Username" value={username} onChange={(e) => setUsername(e.target.value)} />
          <TextField fullWidth label="API Token" type="password" placeholder="Enter new token (leave blank to keep current)" value={token} onChange={(e) => setToken(e.target.value)} />

          <Button variant="contained" onClick={handleSave} disabled={status === 'saving'}>
            {status === 'saving' ? <CircularProgress size={18} /> : 'Save Settings'}
          </Button>

          {status === 'saved' && <Alert severity="success">Settings saved</Alert>}
          {error && <Alert severity="error">{error}</Alert>}
        </Stack>
      </Paper>

      <Paper sx={{ p: 3, mt: 3, maxWidth: 600 }}>
        <Typography variant="h6" gutterBottom>Service Endpoints</Typography>
        <Typography variant="body2" color="text.secondary" gutterBottom>
          Connected Railway services for RAG search and CIM topology.
        </Typography>
        <Stack spacing={1} sx={{ mt: 1 }}>
          <Chip label="n8n RAG Search" icon={<CheckCircleIcon />} color="success" variant="outlined" />
          <Chip label="CIMGraph API" icon={<CheckCircleIcon />} color="success" variant="outlined" />
          <Chip label="Blazegraph SPARQL" icon={<CheckCircleIcon />} color="success" variant="outlined" />
        </Stack>
      </Paper>
    </Box>
  );
}
