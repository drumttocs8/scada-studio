import React, { useCallback, useState } from 'react';
import { Box, Typography, Paper, Button, Alert, LinearProgress, Chip, Stack } from '@mui/material';
import CloudUploadIcon from '@mui/icons-material/CloudUpload';
import { configApi } from '../services/api';
import { validateXml, validateExpFile } from '../utils/validator';

interface FileUploadProps {
  onUploadComplete?: () => void;
}

export default function FileUpload({ onUploadComplete }: FileUploadProps) {
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);

  const handleFile = useCallback(async (file: File) => {
    setError(null);
    setResult(null);

    // Client-side validation
    if (file.name.toLowerCase().endsWith('.exp')) {
      const v = validateExpFile(file.name);
      if (v.warnings.length) setError(v.warnings.join('. '));
      return;
    }

    if (file.name.toLowerCase().endsWith('.xml')) {
      const text = await file.text();
      const v = validateXml(text);
      if (!v.valid) {
        setError(v.errors.join('. '));
        return;
      }
    }

    setUploading(true);
    try {
      const resp = await configApi.upload(file);
      setResult(resp.data);
      onUploadComplete?.();
    } catch (err: any) {
      setError(err.response?.data?.error || err.message);
    } finally {
      setUploading(false);
    }
  }, [onUploadComplete]);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  };

  return (
    <Box>
      <Paper
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        sx={{
          p: 4, textAlign: 'center', cursor: 'pointer',
          border: '2px dashed', borderColor: dragOver ? 'primary.main' : 'divider',
          bgcolor: dragOver ? 'action.hover' : 'transparent',
          transition: 'all 0.2s',
        }}
      >
        <CloudUploadIcon sx={{ fontSize: 48, color: 'primary.main', mb: 1 }} />
        <Typography variant="h6">Drop RTAC XML file here</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          or click to browse (.xml files)
        </Typography>
        <Button variant="outlined" component="label">
          Choose File
          <input type="file" hidden accept=".xml,.json" onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])} />
        </Button>
      </Paper>

      {uploading && <LinearProgress sx={{ mt: 1 }} />}
      {error && <Alert severity="warning" sx={{ mt: 2 }}>{error}</Alert>}
      {result && (
        <Alert severity="success" sx={{ mt: 2 }}>
          <Typography variant="subtitle2">Uploaded: {result.filename}</Typography>
          <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
            <Chip label={`${result.devices} devices`} size="small" color="primary" />
            <Chip label={`${result.points} points`} size="small" color="secondary" />
            {result.tagMappings > 0 && <Chip label={`${result.tagMappings} tag mappings`} size="small" />}
          </Stack>
        </Alert>
      )}
    </Box>
  );
}
