import React, { useState } from 'react';
import AppBar from '@mui/material/AppBar';
import Toolbar from '@mui/material/Toolbar';
import Typography from '@mui/material/Typography';
import IconButton from '@mui/material/IconButton';
import MenuIcon from '@mui/icons-material/Menu';
import Drawer from '@mui/material/Drawer';
import List from '@mui/material/List';
import ListItem from '@mui/material/ListItem';
import ListItemButton from '@mui/material/ListItemButton';
import ListItemText from '@mui/material/ListItemText';
import Box from '@mui/material/Box';

const links = [
  { label: 'Evaluator', href: '#home' },
  { label: 'Overview', href: '#overview' },
  { label: 'Contact', href: '#contact' },
];

function NavBar() {
  const [open, setOpen] = useState(false);

  const toggle = () => setOpen(!open);

  const renderLinks = (vertical = false) => (
    <Box
      sx={{
        display: vertical ? 'block' : { xs: 'none', md: 'flex' },
        ml: vertical ? 0 : 2,
      }}
    >
      {links.map(({ label, href }) => (
        <Box key={label} component="a" href={href} sx={{
          color: '#fff', textDecoration: 'none', mx: vertical ? 0 : 2, my: vertical ? 1 : 0,
          '&:hover': { color: '#ff6f00' },
        }} onClick={() => setOpen(false)}>
          {label}
        </Box>
      ))}
    </Box>
  );

  return (
    <>
      <AppBar position="fixed" sx={{ bgcolor: '#000' }}>
        <Toolbar sx={{ justifyContent: 'space-between' }}>
          <Typography variant="h6" component="a" href="#home" sx={{ color: '#ff6f00', textDecoration: 'none' }}>
            AMIE
          </Typography>

          {/* Desktop links */}
          {renderLinks(false)}

          {/* Mobile menu button */}
          <IconButton edge="end" color="inherit" sx={{ display: { md: 'none' } }} onClick={toggle}>
            <MenuIcon />
          </IconButton>
        </Toolbar>
      </AppBar>

      {/* Offset */}
      <Toolbar />

      {/* Mobile drawer */}
      <Drawer anchor="right" open={open} onClose={toggle} sx={{ display: { md: 'none' } }}>
        <Box sx={{ width: 200, p: 2, bgcolor: '#111', height: '100%' }}>
          <Typography variant="h6" sx={{ color: '#ff6f00', mb: 2 }}>Menu</Typography>
          {links.map(({ label, href }) => (
            <List key={label} disablePadding>
              <ListItem disablePadding>
                <ListItemButton component="a" href={href} onClick={toggle}>
                  <ListItemText primary={label} sx={{ color: '#fff' }} />
                </ListItemButton>
              </ListItem>
            </List>
          ))}
        </Box>
      </Drawer>
    </>
  );
}

export default NavBar;
