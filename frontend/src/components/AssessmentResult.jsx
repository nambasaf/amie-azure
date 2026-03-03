import React, { useMemo } from 'react';
import {
  Box,
  Typography,
  Paper,
  Button,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Chip,
  Divider,
  List,
  ListItem,
  ListItemText,
  Link,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import DownloadIcon from '@mui/icons-material/Download';
import { jsPDF } from 'jspdf';

function safeJson(str, fallback = null) {
  if (str == null || str === '') return fallback;
  if (typeof str === 'object') return str;
  try {
    return JSON.parse(str);
  } catch {
    return fallback;
  }
}

function AssessmentResult({ fullResult, filename }) {
  const parsed = useMemo(() => {
    if (!fullResult) return null;
    const idca = safeJson(fullResult.idca_output, {});
    const naa = safeJson(fullResult.naa_output, {});
    const aaReport = fullResult.aa_output != null ? String(fullResult.aa_output) : '';
    const status = fullResult.status || 'unknown';
    const completedAt = fullResult.completed_at || fullResult.uploaded_at;
    const requestId = fullResult.request_id || fullResult.RowKey || '';

    return {
      idca,
      naa,
      aaReport,
      status,
      completedAt,
      requestId,
      citation: idca.source_citation || idca.citation || '—',
      determination: idca.status_determination || '—',
      justification: idca.justification || '—',
      ucs: naa.ucs || '—',
      ssSynopsis: naa.ss_synopsis || '—',
      lor: Array.isArray(naa.lor) ? naa.lor : [],
      assessments: Array.isArray(naa.assessments) ? naa.assessments : [],
    };
  }, [fullResult]);

  const handleDownloadPdf = () => {
    if (!parsed) return;
    const doc = new jsPDF({ putOnlyUsedFonts: true });
    const margin = 20;
    const pageW = doc.internal.pageSize.getWidth();
    const pageH = doc.internal.pageSize.getHeight();
    let y = margin;
    const lineH = 6;
    const sectionGap = 12;
    const orange = [255, 111, 0];
    const dark = [32, 32, 32];

    const addText = (text, opts = {}) => {
      const { font = 'helvetica', size = 10, bold = false } = opts;
      doc.setFont(font, bold ? 'bold' : 'normal');
      doc.setFontSize(size);
      const lines = doc.splitTextToSize(String(text), pageW - 2 * margin);
      lines.forEach((line) => {
        if (y > pageH - 25) {
          doc.addPage();
          y = margin;
          doc.setDrawColor(...orange);
          doc.setLineWidth(0.5);
          doc.line(margin, y - 4, pageW - margin, y - 4);
          y += 6;
        }
        doc.text(line, margin, y);
        y += lineH;
      });
    };

    // Header bar (AMIE branding)
    doc.setFillColor(...orange);
    doc.rect(0, 0, pageW, 36, 'F');
    doc.setTextColor(255, 255, 255);
    doc.setFontSize(22);
    doc.setFont('helvetica', 'bold');
    doc.text('AMIE', margin, 14);
    doc.setFontSize(11);
    doc.setFont('helvetica', 'normal');
    doc.text('Academic Manuscript IP Evaluator', margin, 24);
    doc.setFontSize(9);
    doc.text('Oregon State University — Division of Research & Innovation', pageW - margin, 24, { align: 'right' });
    y = 44;

    doc.setDrawColor(...orange);
    doc.setLineWidth(0.8);
    doc.line(margin, y, pageW - margin, y);
    y += 10;

    doc.setTextColor(0, 0, 0);
    doc.setFontSize(14);
    doc.setFont('helvetica', 'bold');
    doc.setTextColor(...orange);
    doc.text('Assessment Report', margin, y);
    y += 10;
    doc.setFontSize(10);
    doc.setFont('helvetica', 'normal');
    doc.setTextColor(0, 0, 0);
    addText(`Request ID: ${parsed.requestId}`);
    addText(`File: ${filename || fullResult?.filename || '—'}`);
    addText(`Status: ${parsed.status}`);
    addText(`Completed: ${parsed.completedAt ? new Date(parsed.completedAt).toLocaleString() : '—'}`);
    y += sectionGap;

    doc.setDrawColor(200, 200, 200);
    doc.setLineWidth(0.3);
    doc.line(margin, y, pageW - margin, y);
    y += 8;
    doc.setFontSize(12);
    doc.setFont('helvetica', 'bold');
    doc.setTextColor(...orange);
    addText('1. IDCA — Classification', { size: 12, bold: true });
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(10);
    doc.setTextColor(0, 0, 0);
    addText(`Determination: ${parsed.determination}`);
    addText(`Citation: ${parsed.citation}`);
    addText(`Justification: ${parsed.justification}`);
    y += sectionGap;

    doc.setDrawColor(200, 200, 200);
    doc.line(margin, y, pageW - margin, y);
    y += 8;
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(12);
    doc.setTextColor(...orange);
    addText('2. NAA — Prior Art', { size: 12, bold: true });
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(10);
    doc.setTextColor(0, 0, 0);
    addText(`UCS: ${parsed.ucs}`);
    addText(`Source structure synopsis: ${parsed.ssSynopsis}`);
    if (parsed.lor.length) {
      addText('References:');
      parsed.lor.slice(0, 15).forEach((ref, i) => {
        const title = ref.title || ref.reference_citation || '—';
        const source = ref.source || '—';
        addText(`  ${i + 1}. [${source}] ${title}`, { size: 9 });
      });
    }
    y += sectionGap;

    doc.setDrawColor(200, 200, 200);
    doc.line(margin, y, pageW - margin, y);
    y += 8;
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(12);
    doc.setTextColor(...orange);
    addText('3. Final Report — Aggregation Agent', { size: 12, bold: true });
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(9);
    doc.setTextColor(0, 0, 0);
    addText(parsed.aaReport);
    y += sectionGap;

    // Footer on last page
    if (y < pageH - 20) {
      doc.setDrawColor(...orange);
      doc.setLineWidth(0.4);
      doc.line(margin, pageH - 14, pageW - margin, pageH - 14);
      doc.setFontSize(8);
      doc.setTextColor(100, 100, 100);
      doc.text('AMIE v1.0 — Oregon State University, Division of Research & Innovation', pageW / 2, pageH - 8, { align: 'center' });
    }

    doc.save(`AMIE-Assessment-${parsed.requestId || 'report'}.pdf`);
  };

  if (!parsed) return null;

  const isComplete = ['completed', 'assessed'].includes(String(parsed.status).toLowerCase());

  return (
    <Box sx={{ width: '100%', maxWidth: 720, mt: 3 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 2, mb: 2 }}>
        <Typography variant="h6" sx={{ color: 'primary.main', fontWeight: 600 }}>
          Assessment Result
        </Typography>
        {isComplete && (
          <Button
            variant="outlined"
            size="small"
            startIcon={<DownloadIcon />}
            onClick={handleDownloadPdf}
            sx={{ color: 'primary.main', borderColor: 'primary.main', '&:hover': { borderColor: 'primary.light', bgcolor: 'rgba(255,111,0,0.08)' } }}
          >
            Download PDF
          </Button>
        )}
      </Box>

      <Paper elevation={0} sx={{ p: 2, mb: 2, bgcolor: 'rgba(0,0,0,0.25)', border: '1px solid', borderColor: 'primary.main' }}>
        <Typography variant="subtitle2" color="primary.main" gutterBottom>Overview</Typography>
        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mb: 1 }}>
          <Chip label={parsed.status} size="small" color={parsed.status === 'completed' ? 'success' : 'default'} sx={{ fontWeight: 600 }} />
          {parsed.completedAt && (
            <Typography variant="caption" sx={{ color: '#aaa', alignSelf: 'center' }}>
              {new Date(parsed.completedAt).toLocaleString()}
            </Typography>
          )}
        </Box>
        {filename && <Typography variant="body2" sx={{ color: '#ccc' }}>File: {filename}</Typography>}
        {parsed.requestId && <Typography variant="caption" sx={{ color: '#888', fontFamily: 'monospace' }}>Request ID: {parsed.requestId}</Typography>}
      </Paper>

      <Accordion defaultExpanded sx={{ bgcolor: 'rgba(0,0,0,0.2)', border: '1px solid rgba(255,111,0,0.3)', '&:before': { display: 'none' }, mb: 1 }}>
        <AccordionSummary expandIcon={<ExpandMoreIcon sx={{ color: 'primary.main' }} />}>
          <Typography sx={{ color: 'primary.main', fontWeight: 600 }}>IDCA — Classification</Typography>
        </AccordionSummary>
        <AccordionDetails>
          <Typography variant="subtitle2" sx={{ color: '#aaa', mb: 0.5 }}>Determination</Typography>
          <Typography sx={{ color: '#fff', mb: 1.5 }}>{parsed.determination}</Typography>
          <Typography variant="subtitle2" sx={{ color: '#aaa', mb: 0.5 }}>Citation</Typography>
          <Typography sx={{ color: '#fff', mb: 1.5 }}>{parsed.citation}</Typography>
          <Typography variant="subtitle2" sx={{ color: '#aaa', mb: 0.5 }}>Justification</Typography>
          <Typography sx={{ color: '#ddd', whiteSpace: 'pre-wrap' }}>{parsed.justification}</Typography>
        </AccordionDetails>
      </Accordion>

      <Accordion defaultExpanded sx={{ bgcolor: 'rgba(0,0,0,0.2)', border: '1px solid rgba(255,111,0,0.3)', '&:before': { display: 'none' }, mb: 1 }}>
        <AccordionSummary expandIcon={<ExpandMoreIcon sx={{ color: 'primary.main' }} />}>
          <Typography sx={{ color: 'primary.main', fontWeight: 600 }}>NAA — Prior Art</Typography>
        </AccordionSummary>
        <AccordionDetails>
          <Typography variant="subtitle2" sx={{ color: '#aaa', mb: 0.5 }}>Unified Composite Search (UCS)</Typography>
          <Typography sx={{ color: '#ddd', mb: 1.5, fontFamily: 'monospace', fontSize: '0.85rem' }}>{parsed.ucs}</Typography>
          <Typography variant="subtitle2" sx={{ color: '#aaa', mb: 0.5 }}>Source structure synopsis</Typography>
          <Typography sx={{ color: '#ddd', mb: 1.5 }}>{parsed.ssSynopsis}</Typography>
          {parsed.lor.length > 0 && (
            <>
              <Divider sx={{ borderColor: 'rgba(255,111,0,0.3)', my: 1.5 }} />
              <Typography variant="subtitle2" sx={{ color: '#aaa', mb: 1 }}>References ({parsed.lor.length})</Typography>
              <List dense disablePadding>
                {parsed.lor.slice(0, 20).map((ref, i) => (
                  <ListItem key={i} disablePadding sx={{ py: 0.5 }}>
                    <ListItemText
                      primary={
                        <Typography variant="body2" sx={{ color: '#ddd' }}>
                          [{ref.source || '—'}] {ref.title || ref.reference_citation || '—'}
                          {ref.year != null && ` (${ref.year})`}
                        </Typography>
                      }
                      secondary={
                        ref.url ? (
                          <Link href={ref.url} target="_blank" rel="noopener noreferrer" sx={{ fontSize: '0.75rem', color: 'primary.main' }}>
                            Open link
                          </Link>
                        ) : null
                      }
                    />
                  </ListItem>
                ))}
              </List>
            </>
          )}
        </AccordionDetails>
      </Accordion>

      <Accordion defaultExpanded sx={{ bgcolor: 'rgba(0,0,0,0.2)', border: '1px solid rgba(255,111,0,0.3)', '&:before': { display: 'none' }, mb: 1 }}>
        <AccordionSummary expandIcon={<ExpandMoreIcon sx={{ color: 'primary.main' }} />}>
          <Typography sx={{ color: 'primary.main', fontWeight: 600 }}>Final Report — Aggregation Agent</Typography>
        </AccordionSummary>
        <AccordionDetails>
          <Typography
            component="div"
            sx={{
              color: '#ddd',
              whiteSpace: 'pre-wrap',
              fontFamily: 'inherit',
              fontSize: '0.9rem',
              lineHeight: 1.7,
              '& p': { mb: 1 },
            }}
          >
            {parsed.aaReport || (parsed.status === 'assessed' ? 'Aggregation Agent is compiling the final report...' : 'No report available.')}
          </Typography>
        </AccordionDetails>
      </Accordion>
    </Box>
  );
}

export default AssessmentResult;
