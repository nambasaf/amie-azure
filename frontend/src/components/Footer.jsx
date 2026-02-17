import React from 'react';
import { Box, Container, Grid, Typography, Link } from '@mui/material';
import theme from '../theme';

const columns = [
  {
    title: 'AMIE',
    items: [
      { label: 'Academic Manuscript IP Evaluator', href: null },
      { label: 'v1.0', href: null },
    ],
  },
  {
    title: 'Oregon State',
    items: [
      { label: 'Division of Research & Innovation', href: 'https://research.oregonstate.edu' },
      { label: 'OSU Home', href: 'https://oregonstate.edu' },
    ],
  },
];

export default function Footer() {
  return (
    <Box
      component="footer"
      sx={{
        width: '100%',
        mt: 8,
        py: 4,
        px: 2,
        backgroundColor: 'rgba(17,17,17,0.98)',
        borderTop: '1px solid',
        borderColor: 'rgba(255,111,0,0.25)',
        boxShadow: `0 -4px 20px rgba(0,0,0,0.3)`,
      }}
    >
      <Container maxWidth="lg">
        <Grid container spacing={4} justifyContent="space-between" alignItems="flex-start">
          {columns.map((col) => (
            <Grid item xs={12} sm={6} md={3} key={col.title}>
              <Typography
                variant="overline"
                sx={{
                  color: theme.palette.primary.main,
                  fontWeight: 700,
                  letterSpacing: 1.2,
                  display: 'block',
                  mb: 1.5,
                }}
              >
                {col.title}
              </Typography>
              {col.items.map((item) =>
                item.href ? (
                  <Link
                    key={item.label}
                    href={item.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    variant="body2"
                    sx={{
                      display: 'block',
                      color: 'rgba(255,255,255,0.7)',
                      textDecoration: 'none',
                      mb: 0.5,
                      '&:hover': { color: theme.palette.primary.main },
                    }}
                  >
                    {item.label}
                  </Link>
                ) : (
                  <Typography key={item.label} variant="body2" sx={{ color: 'rgba(255,255,255,0.6)', mb: 0.5 }}>
                    {item.label}
                  </Typography>
                )
              )}
            </Grid>
          ))}
          <Grid item xs={12} md={4} sx={{ textAlign: { xs: 'left', md: 'right' } }}>
            <Typography variant="overline" sx={{ color: theme.palette.primary.main, fontWeight: 700, letterSpacing: 1.2, display: 'block', mb: 1.5 }}>
              OSU
            </Typography>
            <Typography variant="body2" sx={{ color: 'rgba(255,255,255,0.5)', fontStyle: 'italic' }}>
              Oregon State University
            </Typography>
            <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.4)', display: 'block', mt: 0.5 }}>
              Innovation &amp; intellectual property evaluation
            </Typography>
          </Grid>
        </Grid>
        <Box sx={{ mt: 3, pt: 2, borderTop: '1px solid rgba(255,255,255,0.08)', textAlign: 'center' }}>
          <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.4)' }}>
            © {new Date().getFullYear()} Oregon State University · AMIE
          </Typography>
        </Box>
      </Container>
    </Box>
  );
}
