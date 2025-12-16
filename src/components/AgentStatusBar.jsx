import React from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import CircularProgress from '@mui/material/CircularProgress';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty';

// status: "pending" | "in_progress" | "done" | "error"
function StatusIcon({ status }) {
  switch (status) {
    case 'in_progress':
      return <CircularProgress size={18} sx={{ color: '#ff6f00' }} />;
    case 'done':
      return <CheckCircleIcon sx={{ color: 'limegreen' }} />;
    case 'error':
      return <ErrorIcon color="error" />;
    default:
      return <HourglassEmptyIcon sx={{ color: 'gray' }} />;
  }
}

function AgentStatusBar({ agents }) {
  return (
    <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap', justifyContent: 'center', mt: 2 }}>
      {agents.map(({ name, status }) => (
        <Box key={name} sx={{ display: 'flex', alignItems: 'center', gap: 1, bgcolor: '#222', px: 1.5, py: 0.5, borderRadius: 1 }}>
          <StatusIcon status={status} />
          <Typography variant="body2" sx={{ color: '#fff' }}>{name}</Typography>
        </Box>
      ))}
    </Box>
  );
}

export default AgentStatusBar;
