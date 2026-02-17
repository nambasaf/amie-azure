import { createTheme, alpha } from '@mui/material';

const theme = createTheme({
  palette: {
    mode: 'dark',
    primary: { main: '#ff6f00' },
    background: {
      default: '#000000',
      paper: '#111111'
    }
  },
  shape: {
    borderRadius: 8
  },
  typography: {
    fontFamily: ['Roboto', 'sans-serif'].join(','),
    h5: { fontWeight: 600 },
    button: { textTransform: 'none', fontWeight: 600 }
  },
  components: {
    MuiAppBar: {
      styleOverrides: {
        root: {
          backgroundColor: alpha('#000', 0.7),
          backdropFilter: 'blur(6px)'
        }
      }
    }
  }
});

export default theme;

