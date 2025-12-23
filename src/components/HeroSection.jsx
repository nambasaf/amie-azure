import React from 'react';
import { Stack, Typography, Paper, Box } from '@mui/material';
import CloudUploadIcon from '@mui/icons-material/CloudUpload';
import UploadDropzone from './UploadDropzone';
import AgentStatusBar from './AgentStatusBar';

export default function HeroSection() {
  return (
    <Stack spacing={4} alignItems="center" sx={{ width: '100%' }}>
      <Paper elevation={3} sx={{ p: 6, textAlign: 'center', border: '2px dashed', borderColor: 'primary.main', bgcolor: 'background.paper', maxWidth: 600 }}>
        <Box display="flex" justifyContent="center" mb={2}>
          <CloudUploadIcon sx={{ fontSize: 64, color: 'primary.main' }} />
        </Box>
        <Typography variant="h6" gutterBottom>
          Drag & drop your manuscript PDF
        </Typography>
        <Typography variant="body2" color="text.secondary" gutterBottom>
          or click below to browse from your computer
        </Typography>
        <Box mt={4}>
          <UploadDropzone />
        </Box>
      </Paper>
      <AgentStatusBar />
    </Stack>
  );
}

