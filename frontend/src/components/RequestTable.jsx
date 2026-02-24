import React, { useEffect, useState } from 'react';
import axios from 'axios';
import {
  Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, Paper, Chip, Typography, CircularProgress, Button, Box
} from '@mui/material';

function statusColor(status) {
  switch (status?.toLowerCase()) {
    case 'assessed':
    case 'completed':
      return 'success';
    case 'failed':
      return 'error';
    case 'retrying':
      return 'warning';
    case 'uploaded':
    case 'in_progress':
      return 'info';
    default:
      return 'default';
  }
}

export default function RequestTable() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(false);

  const fetchData = async () => {
    try {
      setLoading(true);
      const baseUrl = import.meta.env.VITE_API_BASE; // use ingestion host
      const authCode = import.meta.env.VITE_INGESTION_AGENT_FUNCTION_KEY;

      const url = `${baseUrl}/api/requests?code=${authCode}`;
      const { data } = await axios.get(url);

      const sorted = Array.isArray(data)
        ? [...data].sort((a, b) => new Date(b.uploaded_at || b.created_at || b.timestamp || 0) - new Date(a.uploaded_at || a.created_at || a.timestamp || 0))
        : [];
      setRows(sorted);
      setError(null);
    } catch (err) {
      console.error('Failed to fetch request history', err);
      if (err.response?.status === 401) {
        setError('Authentication failed. Check your Azure Function key.');
      } else {
        setError('Failed to load request history. Check console for details.');
      }
      setRows([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  if (loading) return <CircularProgress sx={{ color: '#ff6f00', mt: 2 }} />;
  if (error) return <Typography sx={{ color: '#ff6f00', mt: 2 }}>{error}</Typography>;
  if (rows.length === 0) return <Typography sx={{ color: '#888', mt: 2 }}>No submissions found.</Typography>;

  const displayRows = expanded ? rows : rows.slice(0, 5);
  const hasMore = rows.length > 5;

  return (
    <Box sx={{ width: '100%' }}>
      <TableContainer component={Paper} sx={{ bgcolor: '#111', mt: 2 }}>
        <Table size="small" sx={{ '& th, & td': { color: '#fff', borderColor: '#333' } }}>
          <TableHead>
            <TableRow>
              <TableCell>Filename</TableCell>
              <TableCell>Status</TableCell>
              <TableCell>Uploaded At</TableCell>
              <TableCell>Request ID</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {displayRows.map((row) => (
              <TableRow key={row.request_id}>
                <TableCell>{row.filename}</TableCell>
                <TableCell><Chip label={row.status} color={statusColor(row.status)} size="small" /></TableCell>
                <TableCell>{new Date(row.uploaded_at).toLocaleString()}</TableCell>
                <TableCell sx={{ fontFamily: 'monospace' }}>{row.request_id}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
      {hasMore && (
        <Box sx={{ display: 'flex', justifyContent: 'center', mt: 2 }}>
          <Button
            variant="outlined"
            onClick={() => setExpanded(!expanded)}
            sx={{ color: 'primary.main', borderColor: 'primary.main' }}
          >
            {expanded ? 'Show Less' : `See More... (${rows.length - 5} more)`}
          </Button>
        </Box>
      )}
    </Box>
  );
}
