import React from 'react';
import { Box, Paper } from '@mui/material';
import Editor from '@monaco-editor/react';

interface ConfigEditorProps {
  xml: string;
  filename?: string;
  onChange?: (value: string) => void;
  readOnly?: boolean;
}

export default function ConfigEditor({ xml, filename, onChange, readOnly = true }: ConfigEditorProps) {
  return (
    <Paper sx={{ overflow: 'hidden' }}>
      <Box sx={{ height: 600 }}>
        <Editor
          height="100%"
          language="xml"
          theme="vs-dark"
          value={xml}
          onChange={(v) => onChange?.(v || '')}
          options={{
            readOnly,
            minimap: { enabled: true },
            fontSize: 13,
            wordWrap: 'on',
            scrollBeyondLastLine: false,
            automaticLayout: true,
          }}
          path={filename || 'config.xml'}
        />
      </Box>
    </Paper>
  );
}
