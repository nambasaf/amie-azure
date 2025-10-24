import React from 'react';
import UploadDropzone from './components/UploadDropzone';

function App() {
  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'space-between', backgroundColor: '#000', color: '#fff' }}>
      <header style={{ marginTop: '2rem' }}>
        <h1 style={{ color: '#ff6f00', margin: 0 }}>AMIE</h1>
        <p style={{ textAlign: 'center', marginTop: '0.25rem', fontStyle: 'italic', color: '#fff' }}>
          Academic Manuscript IP Evaluator
        </p>
      </header>

      <main style={{ flexGrow: 1, display: 'flex', alignItems: 'center' }}>
        <UploadDropzone />
      </main>

      <footer style={{ width: '100%', textAlign: 'center', padding: '1rem 0', backgroundColor: '#111', fontSize: '0.9rem' }}>
        <span style={{ color: '#ff6f00' }}>AMIE v1.0</span> &nbsp;|&nbsp; Oregon State University
      </footer>
    </div>
  );
}

export default App;
