import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { Box, AppBar, Toolbar, Typography, Drawer, List, ListItemButton, ListItemIcon, ListItemText, IconButton } from '@mui/material';
import { useNavigate, useLocation } from 'react-router-dom';
import DashboardIcon from '@mui/icons-material/Dashboard';
import UploadFileIcon from '@mui/icons-material/UploadFile';
import EditIcon from '@mui/icons-material/Edit';
import SearchIcon from '@mui/icons-material/Search';
import CompareIcon from '@mui/icons-material/Compare';
import SettingsIcon from '@mui/icons-material/Settings';
import MenuIcon from '@mui/icons-material/Menu';
import Dashboard from './pages/Dashboard';
import Editor from './pages/Editor';
import Query from './pages/Query';
import Diff from './pages/Diff';
import Settings from './pages/Settings';

const DRAWER_WIDTH = 220;

const navItems = [
    { label: 'Dashboard', path: '/', icon: <DashboardIcon /> },
    { label: 'Editor', path: '/editor', icon: <EditIcon /> },
    { label: 'Query', path: '/query', icon: <SearchIcon /> },
    { label: 'Diff', path: '/diff', icon: <CompareIcon /> },
    { label: 'Settings', path: '/settings', icon: <SettingsIcon /> },
];

export default function App() {
    const navigate = useNavigate();
    const location = useLocation();
    const [mobileOpen, setMobileOpen] = React.useState(false);

    const drawer = (
        <Box sx={{ mt: 8 }}>
            <List>
                {navItems.map((item) => (
                    <ListItemButton
                        key={item.path}
                        selected={location.pathname === item.path}
                        onClick={() => { navigate(item.path); setMobileOpen(false); }}
                    >
                        <ListItemIcon sx={{ minWidth: 36, color: 'inherit' }}>{item.icon}</ListItemIcon>
                        <ListItemText primary={item.label} />
                    </ListItemButton>
                ))}
            </List>
        </Box>
    );

    return (
        <Box sx={{ display: 'flex', minHeight: '100vh' }}>
            <AppBar position="fixed" sx={{ zIndex: (t) => t.zIndex.drawer + 1, bgcolor: '#0d2137' }}>
                <Toolbar>
                    <IconButton color="inherit" edge="start" onClick={() => setMobileOpen(!mobileOpen)} sx={{ mr: 2, display: { md: 'none' } }}>
                        <MenuIcon />
                    </IconButton>
                    <UploadFileIcon sx={{ mr: 1 }} />
                    <Typography variant="h6" noWrap component="div" sx={{ fontWeight: 700 }}>
                        SCADA Studio
                    </Typography>
                    <Typography variant="caption" sx={{ ml: 1, opacity: 0.6 }}>v0.1.0</Typography>
                </Toolbar>
            </AppBar>

            <Drawer
                variant="permanent"
                sx={{ width: DRAWER_WIDTH, flexShrink: 0, display: { xs: 'none', md: 'block' }, '& .MuiDrawer-paper': { width: DRAWER_WIDTH, bgcolor: '#0d2137' } }}
            >
                {drawer}
            </Drawer>

            <Drawer
                variant="temporary"
                open={mobileOpen}
                onClose={() => setMobileOpen(false)}
                sx={{ display: { xs: 'block', md: 'none' }, '& .MuiDrawer-paper': { width: DRAWER_WIDTH, bgcolor: '#0d2137' } }}
            >
                {drawer}
            </Drawer>

            <Box component="main" sx={{ flexGrow: 1, p: 3, mt: 8, width: { md: `calc(100% - ${DRAWER_WIDTH}px)` } }}>
                <Routes>
                    <Route path="/" element={<Dashboard />} />
                    <Route path="/editor" element={<Editor />} />
                    <Route path="/query" element={<Query />} />
                    <Route path="/diff" element={<Diff />} />
                    <Route path="/settings" element={<Settings />} />
                    <Route path="*" element={<Navigate to="/" />} />
                </Routes>
            </Box>
        </Box>
    );
}
