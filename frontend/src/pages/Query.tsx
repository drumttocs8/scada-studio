import React, { useState } from 'react';
import { Box, Typography, TextField, Button, Paper, Tabs, Tab, CircularProgress, Alert } from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import { queryApi } from '../services/api';

export default function Query() {
  const [tab, setTab] = useState(0);
  const [query, setQuery] = useState('');
  const [sparql, setSparql] = useState('');
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSearch = async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await queryApi.search(query);
      setResult(resp.data);
    } catch (err: any) {
      setError(err.response?.data?.error || err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleTopology = async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = tab === 1
        ? await queryApi.cimTopology(query)
        : await queryApi.sparql(sparql);
      setResult(resp.data);
    } catch (err: any) {
      setError(err.response?.data?.error || err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box>
      <Typography variant="h4" gutterBottom sx={{ fontWeight: 700 }}>Query & Search</Typography>

      <Tabs value={tab} onChange={(_, v) => { setTab(v); setResult(null); setError(null); }} sx={{ mb: 2 }}>
        <Tab icon={<SearchIcon />} label="RAG Search" />
        <Tab icon={<AccountTreeIcon />} label="CIM Topology" />
        <Tab label="SPARQL" />
      </Tabs>

      {tab === 0 && (
        <Box>
          <TextField
            fullWidth label="Search query" placeholder="e.g. What DNP points are configured for transformer protection?"
            value={query} onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            sx={{ mb: 2 }}
          />
          <Button variant="contained" onClick={handleSearch} disabled={loading || !query} startIcon={loading ? <CircularProgress size={18} /> : <SearchIcon />}>
            Search
          </Button>
        </Box>
      )}

      {tab === 1 && (
        <Box>
          <TextField
            fullWidth label="Topology query" placeholder="e.g. Show all transformers in substation MainSub"
            value={query} onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleTopology()}
            sx={{ mb: 2 }}
          />
          <Button variant="contained" onClick={handleTopology} disabled={loading || !query}>
            {loading ? <CircularProgress size={18} /> : 'Query Topology'}
          </Button>
        </Box>
      )}

      {tab === 2 && (
        <Box>
          <TextField
            fullWidth multiline rows={6} label="SPARQL Query"
            placeholder="SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 10"
            value={sparql} onChange={(e) => setSparql(e.target.value)}
            sx={{ mb: 2, fontFamily: 'monospace' }}
          />
          <Button variant="contained" onClick={handleTopology} disabled={loading || !sparql}>
            {loading ? <CircularProgress size={18} /> : 'Execute SPARQL'}
          </Button>
        </Box>
      )}

      {error && <Alert severity="error" sx={{ mt: 2 }}>{error}</Alert>}

      {result && (
        <Paper sx={{ mt: 3, p: 2, maxHeight: 500, overflow: 'auto' }}>
          <Typography variant="h6" gutterBottom>Results</Typography>
          <pre style={{ fontSize: 13, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
            {JSON.stringify(result, null, 2)}
          </pre>
        </Paper>
      )}
    </Box>
  );
}
