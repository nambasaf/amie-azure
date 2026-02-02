import React from 'react';
import HeroSection from './components/HeroSection';
import HowItWorks from './components/HowItWorks';
import RequestTable from './components/RequestTable';
import Footer from './components/Footer';
import FadeIn from './components/FadeIn';
import { ThemeProvider, CssBaseline, Container, Stack } from '@mui/material';
import theme from './theme';
import AppBar from '@mui/material/AppBar';
import Toolbar from '@mui/material/Toolbar';
import Typography from '@mui/material/Typography';
import Box from '@mui/material/Box';


function App() {
  return (
    <ThemeProvider theme={theme}>
      {/* sophisticated animated background */}
      <Box
        sx={{
          position: 'fixed',
          inset: 0,
          zIndex: -1,
          overflow: 'hidden',
          background: '#000000',
          '&::before': {
            content: '""',
            position: 'absolute',
            top: '-10%',
            left: '-10%',
            right: '-10%',
            bottom: '-10%',
            width: '120%',
            height: '120%',
            background: `
              radial-gradient(circle at 20% 30%, rgba(255,110,0,.2) 0%, transparent 50%),
              radial-gradient(circle at 80% 70%, rgba(255,110,0,.15) 0%, transparent 50%),
              radial-gradient(circle at 50% 50%, rgba(255,110,0,.08) 0%, transparent 70%),
              linear-gradient(135deg, rgba(255,110,0,.03) 0%, transparent 50%),
              linear-gradient(45deg, rgba(255,110,0,.02) 0%, transparent 50%)
            `,
            animation: 'gradientShift 25s ease infinite',
            '@keyframes gradientShift': {
              '0%, 100%': { transform: 'translate(0, 0)' },
              '33%': { transform: 'translate(-1%, 1%)' },
              '66%': { transform: 'translate(1%, -1%)' },
            },
          },
          '&::after': {
            content: '""',
            position: 'absolute',
            top: '-10%',
            left: '-10%',
            right: '-10%',
            bottom: '-10%',
            width: '120%',
            height: '120%',
            backgroundImage: `
              repeating-linear-gradient(0deg, transparent, transparent 8px, rgba(255,110,0,.15) 8px, rgba(255,110,0,.15) 9px),
              repeating-linear-gradient(90deg, transparent, transparent 8px, rgba(255,110,0,.15) 8px, rgba(255,110,0,.15) 9px)
            `,
            backgroundSize: '80px 80px',
            opacity: 0.3,
            animation: 'gridMove 20s linear infinite',
            '@keyframes gridMove': {
              '0%': { transform: 'translate(0, 0)' },
              '100%': { transform: 'translate(80px, 80px)' },
            },
          },
        }}
      />
      {/* Pixel LED OSU display */}
      <Box
        sx={{
          position: 'fixed',
          top: '50%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          zIndex: -1,
          fontFamily: 'monospace',
          fontSize: 'clamp(80px, 15vw, 200px)',
          fontWeight: 900,
          color: 'rgba(255,110,0,.12)',
          letterSpacing: '0.15em',
          textShadow: `
            0 0 10px rgba(255,110,0,.2),
            0 0 20px rgba(255,110,0,.15),
            0 0 30px rgba(255,110,0,.1)
          `,
          userSelect: 'none',
          pointerEvents: 'none',
          animation: 'flashPrint 6s ease-in-out infinite',
          '@keyframes flashPrint': {
            '0%': { 
              opacity: 0,
              textShadow: '0 0 0px rgba(255,110,0,0)',
            },
            '10%': { 
              opacity: 0.15,
              textShadow: '0 0 20px rgba(255,110,0,.3), 0 0 40px rgba(255,110,0,.2)',
            },
            '20%': { 
              opacity: 0.12,
              textShadow: '0 0 10px rgba(255,110,0,.2), 0 0 20px rgba(255,110,0,.15)',
            },
            '30%': { 
              opacity: 0.18,
              textShadow: '0 0 25px rgba(255,110,0,.35), 0 0 50px rgba(255,110,0,.25)',
            },
            '40%': { 
              opacity: 0.12,
              textShadow: '0 0 10px rgba(255,110,0,.2), 0 0 20px rgba(255,110,0,.15)',
            },
            '50%': { 
              opacity: 0.15,
              textShadow: '0 0 20px rgba(255,110,0,.3), 0 0 40px rgba(255,110,0,.2)',
            },
            '60%': { 
              opacity: 0.12,
              textShadow: '0 0 10px rgba(255,110,0,.2), 0 0 20px rgba(255,110,0,.15)',
            },
            '70%': { 
              opacity: 0.18,
              textShadow: '0 0 25px rgba(255,110,0,.35), 0 0 50px rgba(255,110,0,.25)',
            },
            '80%': { 
              opacity: 0.12,
              textShadow: '0 0 10px rgba(255,110,0,.2), 0 0 20px rgba(255,110,0,.15)',
            },
            '90%, 100%': { 
              opacity: 0.1,
              textShadow: '0 0 5px rgba(255,110,0,.1)',
            },
          },
        }}
      >
        OSU
      </Box>
      {/* architectural silhouette effect */}
      <Box
        sx={{
          position: 'fixed',
          bottom: 0,
          left: 0,
          right: 0,
          height: '40%',
          zIndex: -1,
          background: `
            linear-gradient(to top, 
              rgba(17,17,17,0.95) 0%,
              rgba(17,17,17,0.7) 30%,
              transparent 100%
            )
          `,
          '&::before': {
            content: '""',
            position: 'absolute',
            bottom: 0,
            left: 0,
            right: 0,
            height: '200px',
            backgroundImage: `
              polygon(0% 100%, 5% 85%, 8% 100%, 12% 70%, 15% 100%, 20% 60%, 25% 100%, 30% 75%, 35% 100%, 40% 80%, 45% 100%, 50% 65%, 55% 100%, 60% 90%, 65% 100%, 70% 55%, 75% 100%, 80% 70%, 85% 100%, 90% 85%, 95% 100%, 100% 100%)
            `,
            backgroundSize: '100% 100%',
            opacity: 0.15,
            filter: 'blur(1px)',
          },
        }}
      />
      <CssBaseline />
      <AppBar position="static" elevation={0} sx={{ borderBottom: '1px solid', borderColor: 'primary.main', boxShadow: `0 0 6px 0 ${theme.palette.primary.main}` }}>
        <Toolbar sx={{ flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center', py: 1.5, px: 2, gap: 1 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <Typography component="a" href="#" variant="h6" sx={{ color: 'primary.main', fontWeight: 700, letterSpacing: 1, textDecoration: 'none', '&:hover': { color: 'primary.light' } }}>
              AMIE
            </Typography>
            <Typography variant="caption" sx={{ color: '#aaa', fontStyle: 'italic', borderLeft: '1px solid rgba(255,111,0,0.4)', pl: 2 }}>
              Academic Manuscript IP Evaluator
            </Typography>
          </Box>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
            <Typography component="a" href="https://research.oregonstate.edu" target="_blank" rel="noopener noreferrer" variant="body2" sx={{ color: '#ccc', textDecoration: 'none', '&:hover': { color: 'primary.main' } }}>
              Division of Research &amp; Innovation
            </Typography>
            <Typography sx={{ color: 'rgba(255,255,255,0.3)' }}>|</Typography>
            <Typography component="a" href="https://oregonstate.edu" target="_blank" rel="noopener noreferrer" variant="body2" sx={{ color: '#ccc', textDecoration: 'none', '&:hover': { color: 'primary.main' } }}>
              OSU Home
            </Typography>
          </Box>
        </Toolbar>
      </AppBar>

      <Container maxWidth="md" sx={{ py: 4 }}>
        <Stack spacing={8}>
          <HeroSection />
          <HowItWorks />
          <FadeIn direction="up" distance={20}>
            <RequestTable />
          </FadeIn>
        </Stack>
      </Container>

      <Footer />
    </ThemeProvider>
  );
}

export default App;
