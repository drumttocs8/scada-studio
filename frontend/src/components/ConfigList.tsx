import React from 'react';
import { List, ListItemButton, ListItemText, ListItemIcon, Typography, Chip, Stack } from '@mui/material';
import DescriptionIcon from '@mui/icons-material/Description';
import { ConfigSummary } from '../store';

interface ConfigListProps {
  configs: ConfigSummary[];
  selectedId?: string | null;
  onSelect: (id: string) => void;
}

export default function ConfigList({ configs, selectedId, onSelect }: ConfigListProps) {
  if (configs.length === 0) {
    return <Typography color="text.secondary" sx={{ p: 2 }}>No configurations uploaded yet.</Typography>;
  }

  return (
    <List>
      {configs.map((config) => (
        <ListItemButton key={config.id} selected={config.id === selectedId} onClick={() => onSelect(config.id)}>
          <ListItemIcon><DescriptionIcon /></ListItemIcon>
          <ListItemText
            primary={config.filename}
            secondary={
              <Stack direction="row" spacing={0.5} sx={{ mt: 0.5 }}>
                <Chip label={`${config.devices} dev`} size="small" variant="outlined" />
                <Chip label={`${config.points} pts`} size="small" variant="outlined" />
              </Stack>
            }
          />
        </ListItemButton>
      ))}
    </List>
  );
}
