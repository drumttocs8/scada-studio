import React, { useState } from 'react';
import { Box, Typography, Grid, Button, CircularProgress, Alert } from '@mui/material';
import CompareIcon from '@mui/icons-material/Compare';
import { diffApi } from '../services/api';
import DiffViewer from '../components/DiffViewer';

export default function Diff() {
  const [xml1, setXml1] = useState('');
  const [xml2, setXml2] = useState('');
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleFile = (setter: (v: string) => void) => (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      const reader = new FileReader();
      reader.onload = (ev) => setter(ev.target?.result as string);
      reader.readAsText(file);
    }
  };

  const handleCompare = async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await diffApi.compare(xml1, xml2);
      setResult(resp.data);
    } catch (err: any) {
      setError(err.response?.data?.error || err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box>
      <Typography variant="h4" gutterBottom sx={{ fontWeight: 700 }}>XML Diff</Typography>
      <Typography color="text.secondary" gutterBottom>
        Compare two RTAC XML configuration files to see changes.
      </Typography>

      <Grid container spacing={2} sx={{ mt: 1 }}>
        <Grid item xs={12} md={6}>
          <Button variant="outlined" component="label" fullWidth>
            Upload Original XML
            <input type="file" hidden accept=".xml" onChange={handleFile(setXml1)} />
          </Button>
          {xml1 && <Typography variant="caption" sx={{ mt: 1, display: 'block' }}>{xml1.length} chars loaded</Typography>}
        </Grid>
        <Grid item xs={12} md={6}>
          <Button variant="outlined" component="label" fullWidth>
            Upload Modified XML
            <input type="file" hidden accept=".xml" onChange={handleFile(setXml2)} />
          </Button>
          {xml2 && <Typography variant="caption" sx={{ mt: 1, display: 'block' }}>{xml2.length} chars loaded</Typography>}
        </Grid>
      </Grid>

      <Button
        variant="contained" sx={{ mt: 2 }} onClick={handleCompare}
        disabled={loading || !xml1 || !xml2}
        startIcon={loading ? <CircularProgress size={18} /> : <CompareIcon />}
      >
        Compare
      </Button>

      {error && <Alert severity="error" sx={{ mt: 2 }}>{error}</Alert>}
      {result && <DiffViewer diff={result} />}
    </Box>
  );
}
