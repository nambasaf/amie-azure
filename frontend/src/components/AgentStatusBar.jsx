import React, { useState, useEffect } from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import CircularProgress from '@mui/material/CircularProgress';
import LinearProgress from '@mui/material/LinearProgress';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty';

// Map backend status strings to icon + color + label
// Maps any status we might receive (backend or frontend) to an icon + label
// Map backend status strings to icon + color + label
// Maps any status we might receive (backend or frontend) to an icon + label
function getStatusUI(status, agentName) {
  switch ((status || '').toLowerCase()) {
    /* --- backend strings --- */
    case 'uploaded':
    case 'queued':
      return { icon: <HourglassEmptyIcon sx={{ color: 'gray' }} />, label: 'Queued' };
    case 'classifying':
      return { icon: <CircularProgress size={18} sx={{ color: '#ff6f00' }} />, label: 'Running' };
    case 'classified':
      return { icon: <CheckCircleIcon sx={{ color: 'limegreen' }} />, label: 'Done' };
    case 'analyzing':
      return { icon: <CircularProgress size={18} sx={{ color: '#ff6f00' }} />, label: 'Running' };
    case 'assessed':
      // 'assessed' means NAA is done, but for AA it means in progress
      if (agentName === 'AA') {
        return { icon: <CircularProgress size={18} sx={{ color: '#ff6f00' }} />, label: 'Running' };
      }
      return { icon: <CheckCircleIcon sx={{ color: 'limegreen' }} />, label: 'Done' };
    case 'failed':
      return { icon: <ErrorIcon color="error" />, label: 'Failed' };

    /* --- legacy frontend strings --- */
    case 'pending':
      return { icon: <HourglassEmptyIcon sx={{ color: 'gray' }} />, label: 'Pending' };
    case 'in_progress':
      return { icon: <CircularProgress size={18} sx={{ color: '#ff6f00' }} />, label: 'Running' };
    case 'done':
      return { icon: <CheckCircleIcon sx={{ color: 'limegreen' }} />, label: 'Done' };
    case 'error':
      return { icon: <ErrorIcon color="error" />, label: 'Error' };
    default:
      return { icon: <HourglassEmptyIcon sx={{ color: 'gray' }} />, label: status || 'Unknown' };
  }
}

// Estimated durations for each agent (in seconds)
const AGENT_DURATIONS = {
  'Ingestion': 5,
  'IDCA': 45,
  'NAA': 90,
  'AA': 15,
};

function AgentStatusBar({ agents = [] }) {
  const [startTimes, setStartTimes] = useState({});
  const [progress, setProgress] = useState({});

  // Track when agents start and calculate progress
  useEffect(() => {
    if (!agents) return;

    agents.forEach(({ name, status }) => {
      // Determine if agent is active based on status and agent name
      const isActive = status === 'in_progress' ||
        status === 'classifying' ||
        status === 'analyzing' ||
        (status === 'assessed' && name === 'AA') || // AA is active when status is 'assessed'
        (name === 'Ingestion' && status === 'uploaded');

      if (isActive) {
        setStartTimes(prev => {
          // Only set start time if not already set (don't reset if already active)
          if (!prev[name]) {
            return { ...prev, [name]: Date.now() };
          }
          return prev;
        });
      }

      // Determine if agent is complete
      const isComplete = status === 'done' ||
        status === 'classified' ||
        (status === 'assessed' && name === 'NAA') || // NAA is complete when status is 'assessed'
        status === 'error' ||
        status === 'failed';

      if (isComplete) {
        setStartTimes(prev => {
          const newTimes = { ...prev };
          delete newTimes[name];
          return newTimes;
        });
        setProgress(prev => {
          const newProgress = { ...prev };
          newProgress[name] = 100;
          return newProgress;
        });
      } else if (status === 'pending' || status === 'queued') {
        // Reset progress when status goes back to pending/queued (e.g. retry)
        setStartTimes(prev => {
          const newTimes = { ...prev };
          delete newTimes[name];
          return newTimes;
        });
        setProgress(prev => {
          const newProgress = { ...prev };
          newProgress[name] = 0;
          return newProgress;
        });
      }
    });
  }, [agents]); // Removed startTimes from dependencies to prevent infinite loop

  // Update progress every 200ms for smooth real-time updates
  useEffect(() => {
    const interval = setInterval(() => {
      const now = Date.now();
      const newProgress = {};

      Object.keys(startTimes).forEach(name => {
        const elapsed = (now - startTimes[name]) / 1000; // seconds
        const duration = AGENT_DURATIONS[name] || 30;
        // Use exponential easing for more realistic progress (starts fast, slows near end)
        const linearProgress = Math.min(0.95, elapsed / duration);
        const easedProgress = linearProgress < 0.5
          ? 2 * linearProgress * linearProgress
          : 1 - Math.pow(-2 * linearProgress + 2, 2) / 2;
        const calculatedProgress = Math.min(95, easedProgress * 100);
        newProgress[name] = Math.round(calculatedProgress * 10) / 10; // Round to 1 decimal
      });

      setProgress(prev => ({ ...prev, ...newProgress }));
    }, 200); // Update every 200ms for smooth animation

    return () => clearInterval(interval);
  }, [startTimes]);

  if (!Array.isArray(agents) || agents.length === 0) return null;

  return (
    <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap', justifyContent: 'center', mt: 2, width: '100%' }}>
      {agents.map(({ name, status }) => {
        const { icon, label } = getStatusUI(status, name);
        // Determine if agent is active based on status and agent name
        const isActive = status === 'in_progress' ||
          status === 'classifying' ||
          status === 'analyzing' ||
          (status === 'assessed' && name === 'AA') || // AA is active when status is 'assessed'
          (name === 'Ingestion' && status === 'uploaded');
        // Determine if agent is complete
        const isComplete = status === 'done' ||
          status === 'classified' ||
          (status === 'assessed' && name === 'NAA'); // NAA is complete when status is 'assessed'
        // Use calculated progress if available, otherwise show 0 for pending, 100 for complete, or start at 1% for active
        const currentProgress = progress[name] !== undefined
          ? progress[name]
          : (isComplete ? 100 : isActive ? Math.max(1, progress[name] || 1) : 0);

        return (
          <Box
            key={name}
            sx={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: 0.5,
              bgcolor: '#222',
              px: 2,
              py: 1.5,
              borderRadius: 2,
              minWidth: 140,
              width: '100%',
              maxWidth: 200,
            }}
          >
            {/* Header for Agent Name */}
            <Typography variant="subtitle2" sx={{ color: '#888', fontWeight: 700, textTransform: 'uppercase', fontSize: '0.7rem', mb: 0.5 }}>
              {name}
            </Typography>

            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%' }}>
              {icon}
              <Typography variant="body2" sx={{ color: '#fff', flex: 1, fontWeight: 500 }}>{label}</Typography>
              {isActive && (
                <Typography variant="caption" sx={{ color: '#ff6f00', fontWeight: 600, minWidth: '40px', textAlign: 'right' }}>
                  {Math.round(currentProgress)}%
                </Typography>
              )}
            </Box>
            {isActive && (
              <Box sx={{ width: '100%', position: 'relative', mt: 1 }}>
                <LinearProgress
                  variant="determinate"
                  value={currentProgress}
                  sx={{
                    width: '100%',
                    height: 4,
                    borderRadius: 2,
                    bgcolor: 'rgba(255,255,255,0.1)',
                    '& .MuiLinearProgress-bar': {
                      bgcolor: '#ff6f00',
                      borderRadius: 2,
                      transition: 'transform 0.2s linear',
                    },
                  }}
                />
              </Box>
            )}
          </Box>
        );
      })}
    </Box>
  );
}

export default AgentStatusBar;
