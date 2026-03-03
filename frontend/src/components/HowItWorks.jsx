import React from 'react';
import { Grid, Typography, Paper, Box } from '@mui/material';
import FileUploadIcon from '@mui/icons-material/FileUpload';
import ScienceIcon from '@mui/icons-material/Science';
import InsightsIcon from '@mui/icons-material/Insights';
import FadeIn from './FadeIn';

const steps = [
  {
    icon: <FileUploadIcon sx={{ fontSize: 48, color: 'primary.main' }} />,
    title: 'Upload',
    desc: 'Submit your manuscript PDF securely to AMIE.',
  },
  {
    icon: <ScienceIcon sx={{ fontSize: 48, color: 'primary.main' }} />,
    title: 'Analyze',
    desc: 'IDCA & NAA agents classify inventions and assess novelty.',
  },
  {
    icon: <InsightsIcon sx={{ fontSize: 48, color: 'primary.main' }} />,
    title: 'Get Insights',
    desc: 'Receive structured overlap scores and aggregated report.',
  },
];

export default function HowItWorks() {
  return (
    <Box id="how" sx={{ width: '100%' }}>
      <FadeIn direction="up" distance={20}>
        <Typography variant="h5" sx={{ mb: 3, textAlign: 'center', fontWeight: 600 }}>
          How it works
        </Typography>
      </FadeIn>
      <Grid container spacing={4} justifyContent="center">
        {steps.map((s, i) => (
          <Grid item xs={12} sm={4} key={s.title}>
            <FadeIn direction="up" delay={120 * (i + 1)} distance={28} duration={550}>
              <Paper
                elevation={2}
                sx={{
                  p: 3,
                  textAlign: 'center',
                  bgcolor: 'background.paper',
                  height: '100%',
                  transition: 'transform 0.25s ease, box-shadow 0.25s ease',
                  '&:hover': {
                    transform: 'translateY(-4px)',
                    boxShadow: '0 12px 28px rgba(0,0,0,0.35)',
                  },
                }}
              >
                {s.icon}
                <Typography variant="subtitle1" sx={{ mt: 1, fontWeight: 600 }}>
                  {s.title}
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                  {s.desc}
                </Typography>
              </Paper>
            </FadeIn>
          </Grid>
        ))}
      </Grid>
    </Box>
  );
}

