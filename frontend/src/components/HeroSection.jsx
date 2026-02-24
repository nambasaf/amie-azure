import React from 'react';
import { Stack, Typography, Paper, Box } from '@mui/material';
import CloudUploadIcon from '@mui/icons-material/CloudUpload';
import UploadDropzone from './UploadDropzone';
import AgentStatusBar from './AgentStatusBar';
import FadeIn from './FadeIn';

export default function HeroSection() {
  return (
    <Stack spacing={4} alignItems="center" sx={{ width: '100%' }}>
      <FadeIn direction="up" distance={32} duration={700}>
        <Box sx={{ textAlign: 'center', mb: 2 }}>
          <Typography variant="h4" sx={{ fontWeight: 700, color: 'primary.main', letterSpacing: 0.5, mb: 0.5 }}>
            Evaluate your manuscript
          </Typography>
          <Typography variant="body1" color="text.secondary">
            Get prior-art overlap and IP assessment in one place
          </Typography>
        </Box>
      </FadeIn>
      <FadeIn direction="up" delay={100} distance={24} duration={600}>
        <Paper
          elevation={3}
          sx={{
            p: 6,
            textAlign: 'center',
            border: '2px dashed',
            borderColor: 'primary.main',
            bgcolor: 'background.paper',
            maxWidth: 600,
            transition: 'box-shadow 0.3s ease, border-color 0.3s ease',
            '&:hover': {
              boxShadow: `0 8px 32px rgba(255,111,0,0.15)`,
              borderColor: 'primary.light',
            },
          }}
        >
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
      </FadeIn>
      <FadeIn direction="up" delay={200}>
        <AgentStatusBar />
      </FadeIn>
    </Stack>
  );
}

