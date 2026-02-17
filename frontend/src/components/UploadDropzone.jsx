import React, { useCallback, useState, useEffect, useRef } from 'react';
import { useDropzone } from 'react-dropzone';
import axios from 'axios';
import Typography from '@mui/material/Typography';
import Box from '@mui/material/Box';
import Paper from '@mui/material/Paper';
import Accordion from '@mui/material/Accordion';
import AccordionSummary from '@mui/material/AccordionSummary';
import AccordionDetails from '@mui/material/AccordionDetails';
import AgentStatusBar from './AgentStatusBar';
import AssessmentResult from './AssessmentResult';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';

const baseStyle = {
  width: '100%',
  maxWidth: 480,
  boxSizing: 'border-box',
  minHeight: 160,
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  justifyContent: 'center',
  padding: '24px',
  borderWidth: 2,
  borderRadius: 2,
  borderColor: '#ff6f00',
  borderStyle: 'dashed',
  backgroundColor: '#111',
  color: '#fff',
  outline: 'none',
  transition: 'border .24s ease-in-out'
};

const AGENT_ORDER = ['Ingestion', 'IDCA', 'NAA', 'AA'];

function getAgentStatusWeight(status) {
  switch (status?.toLowerCase()) {
    case 'error':
    case 'failed':
      return 4; // Final failure state
    case 'done':
    case 'classified':
    case 'assessed':
    case 'completed':
      return 3; // Success state
    case 'in_progress':
    case 'classifying':
    case 'analyzing':
    case 'retrying':
      return 2; // Active state
    case 'uploaded':
    case 'queued':
      return 1; // Waiting state
    default:
      return 0; // Pending/Unknown
  }
}

function mergeAgents(prevAgents, newStatus) {
  const nextAgents = [...prevAgents];

  // Helper to update specific agent if new status is "higher" or equally relevant
  const updateAgent = (index, newStatusStr) => {
    const currentStatus = nextAgents[index].status;
    const currentWeight = getAgentStatusWeight(currentStatus);
    const newWeight = getAgentStatusWeight(newStatusStr);

    // Only update if moving forward, or if it's a retry/failure which overrides specific states
    // Exception: 'retrying' should override 'failed' or 'pending', but not 'done'.
    if (newWeight >= currentWeight || newStatusStr === 'retrying') {
      // Avoid overwriting a 'done' state with 'in_progress' unless logic dictates (e.g. re-running)
      // For this pipeline, once done, usually done. But if we retry, we might go back.
      // Here we implement a simple ratchet: only upgrade weight, or specific overrides.

      if (newStatusStr === 'retrying' && currentStatus === 'failed') {
        nextAgents[index].status = 'retrying';
      } else if (newWeight > currentWeight) {
        nextAgents[index].status = newStatusStr;
      } else if (newWeight === currentWeight && newStatusStr !== currentStatus) {
        // Same weight but different status (e.g. switching active states), take the new one
        nextAgents[index].status = newStatusStr;
      }
    }
  };

  if (!newStatus) return nextAgents;
  const s = newStatus.toLowerCase();

  // 1. Ingestion
  updateAgent(0, 'done');

  // 2. IDCA
  if (['queued', 'uploaded'].includes(s)) {
    updateAgent(1, 'queued');
  } else if (s === 'classifying') {
    updateAgent(1, 'classifying');
  } else if (['classified', 'analyzing', 'assessed', 'completed'].includes(s)) {
    updateAgent(1, 'classified');
  } else if (['failed', 'error'].includes(s) && !nextAgents[1].status.match(/done|classified/)) {
    // Only fail IDCA if it wasn't done
    updateAgent(1, 'failed');
  }

  // 3. NAA
  if (s === 'analyzing') {
    updateAgent(2, 'analyzing');
  } else if (['assessed', 'completed'].includes(s)) {
    updateAgent(2, 'assessed');
  } else if (s === 'failed') {
    updateAgent(2, 'failed');
  }

  // 4. Aggregation Agent
  if (s === 'assessed') {
    updateAgent(3, 'in_progress'); // AA runs after assessment
  } else if (s === 'completed') {
    updateAgent(3, 'done');
  }

  return nextAgents;
}

export default function UploadDropzone({ onStatusChange = () => { } }) {
  const [files, setFiles] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [meta, setMeta] = useState(null);
  const [currentStatus, setCurrentStatus] = useState(null);
  const [fullResult, setFullResult] = useState(null);
  const [agents, setAgents] = useState([
    { name: 'Ingestion', status: 'pending' },
    { name: 'IDCA', status: 'pending' },
    { name: 'NAA', status: 'pending' },
    { name: 'AA', status: 'pending' },
  ]);
  const intervalRef = useRef(null);
  const [authError, setAuthError] = useState(false);
  const [lastStatusUpdate, setLastStatusUpdate] = useState(null);
  const currentStatusRef = useRef(null); // Track current status to prevent infinite loops

  const copyRequestId = async (requestId) => {
    try {
      await navigator.clipboard.writeText(requestId);
      alert('Request ID copied to clipboard!');
    } catch {
      alert('Failed to copy request ID');
    }
  };

  const fetchFullResult = async (requestId) => {
    try {
      const url = `${import.meta.env.VITE_API_BASE}/api/requests/${requestId}?code=${import.meta.env.VITE_API_CODE}`;
      const { data } = await axios.get(url);
      setFullResult(data);
    } catch (err) {
      console.error('Failed to fetch full result from NAA:', err);
    }
  };

  useEffect(() => {
    if (!meta?.request_id) return;

    // Initialize ref with current status
    if (currentStatusRef.current === null && currentStatus) {
      currentStatusRef.current = currentStatus;
    }

    // Stop when pipeline is done: completed (AA done) or failed
    const terminalStatuses = ['completed', 'failed'];
    let pollCount = 0;
    const maxPolls = 600;
    const pollIntervalMs = 2000; // 2s — reduces load on ingestion app

    const pollStatus = async () => {
      try {
        const url = `${import.meta.env.VITE_API_BASE}/api/requests/${meta.request_id}/status?code=${import.meta.env.VITE_INGESTION_AGENT_FUNCTION_KEY}`;
        const { data } = await axios.get(url);

        // Use ref to compare - prevents infinite loops from stale closures
        const previousStatus = currentStatusRef.current;

        // Debug logging to verify backend status updates
        if (data.status !== previousStatus) {
          console.log(`[Status Update] Request ${meta.request_id}: ${previousStatus || 'null'} → ${data.status}`);
          currentStatusRef.current = data.status; // Update ref immediately
          setCurrentStatus(data.status);
          setAgents(prev => mergeAgents(prev, data.status));
          setLastStatusUpdate(new Date().toLocaleTimeString());
          // Trigger fetch if we have something new to show (assessed or terminal)
          const lowerStatus = data.status.toLowerCase();
          if (lowerStatus === 'assessed' || terminalStatuses.includes(lowerStatus)) {
            fetchFullResult(meta.request_id);
          }
        } else if (pollCount % 10 === 0) {
          // Log every 10 polls to show it's still polling
          console.log(`[Status Poll] Request ${meta.request_id}: ${data.status} (poll #${pollCount})`);
          setLastStatusUpdate(new Date().toLocaleTimeString()); // Update timestamp even if status unchanged
        }

        pollCount++;
        if (pollCount >= maxPolls || terminalStatuses.includes(data.status.toLowerCase())) {
          clearInterval(intervalRef.current);
          console.log(`[Status Poll] Stopped polling for ${meta.request_id} (final status: ${data.status})`);
        }
      } catch (err) {
        if (err.response?.status === 401 && !authError) {
          setAuthError(true);
          clearInterval(intervalRef.current);
          console.warn('Auth failed. Check your Azure Function key.');
        } else {
          console.error('Polling status failed:', err);
        }
      }
    };

    pollStatus();
    intervalRef.current = setInterval(pollStatus, pollIntervalMs);
    return () => clearInterval(intervalRef.current);
  }, [meta?.request_id]);

  const onDrop = useCallback(async (acceptedFiles) => {
    const file = acceptedFiles[0];
    if (!file) return;

    setFiles([file]);
    setUploading(true);
    setMeta(null);
    currentStatusRef.current = null; // Reset ref
    setCurrentStatus(null);
    setFullResult(null);
    setAuthError(false);
    setAgents([
      { name: 'Ingestion', status: 'pending' },
      { name: 'IDCA', status: 'pending' },
      { name: 'NAA', status: 'pending' },
      { name: 'AA', status: 'pending' },
    ]);

    try {
      const apiUrl = `${import.meta.env.VITE_API_BASE}/api/upload?code=${import.meta.env.VITE_API_CODE}`;
      const formData = new FormData();
      formData.append('file', file);
      const res = await axios.post(apiUrl, formData);
      setMeta(res.data);
      currentStatusRef.current = 'uploaded'; // Update ref
      setCurrentStatus('uploaded');
      setAgents(prev => mergeAgents(prev, 'uploaded'));
      setFullResult({
        request_id: res.data.request_id,
        filename: res.data.filename,
        message: res.data.message,
        uploaded_at: new Date().toISOString(),
        status: 'uploaded'
      });
    } catch (err) {
      console.error('Upload failed:', err);
      alert('Upload failed');
    } finally {
      setUploading(false);
    }
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { 'application/pdf': ['.pdf'], 'application/msword': ['.doc', '.docx'] }
  });

  return (
    <section style={{ width: '100%', maxWidth: 640 }}>
      <div {...getRootProps({ style: baseStyle })}>
        <input {...getInputProps()} />
        {isDragActive
          ? <p>Drop the files here ...</p>
          : <p>Drag & drop a manuscript here, or click to select files</p>}
      </div>
      <aside style={{ marginTop: '1rem', color: '#ff6f00' }}>
        {uploading && <p>Uploading & processing…</p>}
        {files.map((file) => <p key={file.name}>{file.name} - {file.size} bytes</p>)}
        {meta && (
          <div style={{ marginTop: '1rem', color: '#fff' }}>
            <p>
              Request ID:{' '}
              <span
                onClick={() => copyRequestId(meta.request_id)}
                style={{ fontFamily: 'monospace', cursor: 'pointer', textDecoration: 'underline' }}
              >
                {meta.request_id}
              </span>
            </p>
            {currentStatus && (
              <p>
                Status: <span style={{ color: '#ff6f00' }}>{currentStatus}</span>
                {lastStatusUpdate && (
                  <span style={{ fontSize: '0.75rem', color: '#888', marginLeft: '8px' }}>
                    (last checked: {lastStatusUpdate})
                  </span>
                )}
              </p>
            )}
            {authError && <p style={{ fontSize: '0.875rem' }}>⚠️ Status polling disabled due to invalid key.</p>}
            <AgentStatusBar agents={agents} />
            {fullResult && (
              <Box sx={{ mt: 3, width: '100%' }}>
                {['assessed', 'completed'].includes(currentStatus?.toLowerCase()) ? (
                  <>
                    <AssessmentResult fullResult={fullResult} filename={files[0]?.name} />
                    <Accordion sx={{ mt: 2, bgcolor: 'rgba(0,0,0,0.2)', border: '1px solid rgba(255,111,0,0.2)', '&:before': { display: 'none' } }}>
                      <AccordionSummary expandIcon={<ExpandMoreIcon sx={{ color: 'primary.main' }} />}>
                        <Typography variant="body2" sx={{ color: '#888' }}>Raw JSON</Typography>
                      </AccordionSummary>
                      <AccordionDetails>
                        <Box
                          component="pre"
                          sx={{
                            background: 'rgba(0,0,0,0.3)',
                            borderRadius: 1,
                            p: 2,
                            color: '#aaa',
                            overflow: 'auto',
                            maxHeight: 400,
                            fontSize: '0.75rem',
                            fontFamily: 'monospace',
                            lineHeight: 1.5,
                          }}
                        >
                          {JSON.stringify(fullResult, null, 2)}
                        </Box>
                      </AccordionDetails>
                    </Accordion>
                  </>
                ) : (
                  <Box sx={{ mt: 2 }}>
                    <Typography variant="subtitle2" sx={{ color: 'primary.main', mb: 1.5 }}>Upload Response</Typography>
                    <Paper elevation={0} sx={{ p: 2, bgcolor: 'rgba(0,0,0,0.25)', border: '1px solid rgba(255,111,0,0.3)', borderRadius: 2 }}>
                      <Box sx={{ display: 'grid', gap: 1.5 }}>
                        <Box><Typography component="span" variant="caption" sx={{ color: '#888' }}>Request ID </Typography><Typography component="span" variant="body2" sx={{ fontFamily: 'monospace', color: '#fff' }}>{fullResult.request_id || fullResult.RowKey || '—'}</Typography></Box>
                        <Box><Typography component="span" variant="caption" sx={{ color: '#888' }}>Filename </Typography><Typography component="span" variant="body2" sx={{ color: '#ddd' }}>{fullResult.filename || files[0]?.name || '—'}</Typography></Box>
                        <Box><Typography component="span" variant="caption" sx={{ color: '#888' }}>Status </Typography><Typography component="span" variant="body2" sx={{ color: 'primary.main', fontWeight: 600 }}>{fullResult.status || '—'}</Typography></Box>
                        {fullResult.message && <Box><Typography component="span" variant="caption" sx={{ color: '#888' }}>Message </Typography><Typography component="span" variant="body2" sx={{ color: '#ddd' }}>{fullResult.message}</Typography></Box>}
                        {(fullResult.uploaded_at || fullResult.created_at) && <Box><Typography component="span" variant="caption" sx={{ color: '#888' }}>Uploaded </Typography><Typography component="span" variant="body2" sx={{ color: '#aaa' }}>{new Date(fullResult.uploaded_at || fullResult.created_at).toLocaleString()}</Typography></Box>}
                      </Box>
                    </Paper>
                  </Box>
                )}
              </Box>
            )}
          </div>
        )}
      </aside>
    </section>
  );
}
