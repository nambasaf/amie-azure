import React from 'react';
import NavBar from './NavBar';
import UploadDropzone from './components/UploadDropzone';
import RequestTable from './components/RequestTable';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Container from '@mui/material/Container';
import Paper from '@mui/material/Paper';
import Grid from '@mui/material/Grid';
import Chip from '@mui/material/Chip';

function App() {
  return (
    <Box sx={{ minHeight: '100vh', backgroundColor: '#000', color: '#fff' }}>
      <NavBar />
      
      {/* Home Section - Upload Area */}
      <section id="home" style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '4rem 1rem' }}>
        <Container maxWidth="md">
          <Box sx={{ textAlign: 'center', mb: 4 }}>
            <Typography variant="h2" sx={{ color: '#ff6f00', mb: 2, fontWeight: 'bold' }}>
              AMIE
            </Typography>
            <Typography variant="h5" sx={{ color: '#fff', fontStyle: 'italic', mb: 4 }}>
              Academic Manuscript IP Evaluator
            </Typography>
            <Typography variant="body1" sx={{ color: '#ccc', mb: 4, maxWidth: '600px', mx: 'auto' }}>
              Upload your academic manuscript and receive automated intellectual property evaluation 
              through our multi-agent system. Get insights on novelty, patentability, and prior art analysis.
            </Typography>
          </Box>
          <Box sx={{ display: 'flex', justifyContent: 'center' }}>
            <UploadDropzone />
          </Box>
        </Container>
      </section>

      {/* Overview Section */}
      <section id="overview" style={{ padding: '6rem 1rem', backgroundColor: '#111' }}>
        <Container maxWidth="lg">
          <Typography variant="h3" sx={{ color: '#ff6f00', mb: 4, textAlign: 'center' }}>
            How It Works
          </Typography>
          
          <Grid container spacing={4} sx={{ mb: 6 }}>
            <Grid item xs={12} md={3}>
              <Paper sx={{ p: 3, bgcolor: '#222', textAlign: 'center', height: '100%' }}>
                <Typography variant="h4" sx={{ color: '#ff6f00', mb: 2 }}>1️⃣</Typography>
                <Typography variant="h6" sx={{ color: '#fff', mb: 1 }}>Ingestion</Typography>
                <Typography variant="body2" sx={{ color: '#ccc' }}>
                  Upload your manuscript (PDF or DOCX). The system extracts and prepares your document for analysis.
                </Typography>
              </Paper>
            </Grid>
            
            <Grid item xs={12} md={3}>
              <Paper sx={{ p: 3, bgcolor: '#222', textAlign: 'center', height: '100%' }}>
                <Typography variant="h4" sx={{ color: '#ff6f00', mb: 2 }}>2️⃣</Typography>
                <Typography variant="h6" sx={{ color: '#fff', mb: 1 }}>IDCA</Typography>
                <Typography variant="body2" sx={{ color: '#ccc' }}>
                  Invention Detection and Classification Agent analyzes your manuscript to identify concrete, buildable technologies.
                </Typography>
              </Paper>
            </Grid>
            
            <Grid item xs={12} md={3}>
              <Paper sx={{ p: 3, bgcolor: '#222', textAlign: 'center', height: '100%' }}>
                <Typography variant="h4" sx={{ color: '#ff6f00', mb: 2 }}>3️⃣</Typography>
                <Typography variant="h6" sx={{ color: '#fff', mb: 1 }}>NAA</Typography>
                <Typography variant="body2" sx={{ color: '#ccc' }}>
                  Novelty Assessment Agent performs §102 analysis, searching prior art and evaluating novelty claims.
                </Typography>
              </Paper>
            </Grid>
            
            <Grid item xs={12} md={3}>
              <Paper sx={{ p: 3, bgcolor: '#222', textAlign: 'center', height: '100%' }}>
                <Typography variant="h4" sx={{ color: '#ff6f00', mb: 2 }}>4️⃣</Typography>
                <Typography variant="h6" sx={{ color: '#fff', mb: 1 }}>AA</Typography>
                <Typography variant="body2" sx={{ color: '#ccc' }}>
                  Assessment Agent provides final patentability scoring and comprehensive evaluation report.
                </Typography>
              </Paper>
            </Grid>
          </Grid>

          <Box sx={{ mt: 6 }}>
            <Typography variant="h4" sx={{ color: '#ff6f00', mb: 3, textAlign: 'center' }}>
              Features
            </Typography>
            <Grid container spacing={3}>
              <Grid item xs={12} md={4}>
                <Paper sx={{ p: 3, bgcolor: '#222', height: '100%' }}>
                  <Typography variant="h6" sx={{ color: '#fff', mb: 1 }}>
                    Automated Processing
                  </Typography>
                  <Typography variant="body2" sx={{ color: '#ccc' }}>
                    Multi-agent system processes your manuscript through sequential analysis stages with real-time status updates.
                  </Typography>
                </Paper>
              </Grid>
              
              <Grid item xs={12} md={4}>
                <Paper sx={{ p: 3, bgcolor: '#222', height: '100%' }}>
                  <Typography variant="h6" sx={{ color: '#fff', mb: 1 }}>
                    Prior Art Search
                  </Typography>
                  <Typography variant="body2" sx={{ color: '#ccc' }}>
                    Comprehensive patent database search to identify potential blocking references and evaluate novelty.
                  </Typography>
                </Paper>
              </Grid>
              
              <Grid item xs={12} md={4}>
                <Paper sx={{ p: 3, bgcolor: '#222', height: '100%' }}>
                  <Typography variant="h6" sx={{ color: '#fff', mb: 1 }}>
                    Patentability Scoring
                  </Typography>
                  <Typography variant="body2" sx={{ color: '#ccc' }}>
                    Receive detailed scores and reasoning on the patentability potential of your invention claims.
                  </Typography>
                </Paper>
              </Grid>
            </Grid>
          </Box>

          <Box sx={{ mt: 6, textAlign: 'center' }}>
            <Typography variant="h5" sx={{ color: '#fff', mb: 2 }}>
              Request History
            </Typography>
            <Typography variant="body2" sx={{ color: '#888', mb: 3 }}>
              View all submitted manuscripts and their current processing status
            </Typography>
            <RequestTable />
          </Box>
        </Container>
      </section>

      {/* Contact Section */}
      <section id="contact" style={{ padding: '4rem 1rem', backgroundColor: '#000' }}>
        <Container maxWidth="md">
          <Typography variant="h3" sx={{ color: '#ff6f00', mb: 4, textAlign: 'center' }}>
            Contact & Support
          </Typography>
          <Paper sx={{ p: 4, bgcolor: '#111', textAlign: 'center' }}>
            <Typography variant="body1" sx={{ color: '#ccc', mb: 3 }}>
              For questions, support, or more information about AMIE, please contact:
            </Typography>
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, alignItems: 'center' }}>
              <Chip label="Oregon State University" sx={{ bgcolor: '#222', color: '#ff6f00', fontSize: '1rem', p: 2 }} />
              <Typography variant="body2" sx={{ color: '#888', mt: 2 }}>
                Academic Manuscript IP Evaluator (AMIE) v1.0
              </Typography>
            </Box>
          </Paper>
        </Container>
      </section>

      {/* Footer */}
      <footer style={{ width: '100%', textAlign: 'center', padding: '2rem 0', backgroundColor: '#000', borderTop: '1px solid #333' }}>
        <Container>
          <Typography variant="body2" sx={{ color: '#888' }}>
            <span style={{ color: '#ff6f00', fontWeight: 'bold' }}>AMIE v1.0</span> &nbsp;|&nbsp; 
            <span> Academic Manuscript IP Evaluator </span>&nbsp;|&nbsp; 
            <span> Oregon State University </span>
          </Typography>
          <Typography variant="body2" sx={{ color: '#666', mt: 1 }}>
            © {new Date().getFullYear()} All rights reserved
          </Typography>
        </Container>
      </footer>
    </Box>
  );
}

export default App;
