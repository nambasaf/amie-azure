import React, { useCallback, useState, useEffect } from 'react';
import { useDropzone } from 'react-dropzone';

const baseStyle = {
  flex: 1,
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  padding: '40px',
  borderWidth: 2,
  borderRadius: 2,
  borderColor: '#ff6f00',
  borderStyle: 'dashed',
  backgroundColor: '#111',
  color: '#fff',
  outline: 'none',
  transition: 'border .24s ease-in-out'
};

function UploadDropzone() {
  const [files, setFiles] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [meta, setMeta] = useState(null);

  const onDrop = useCallback(async (acceptedFiles) => {
    const file = acceptedFiles[0];
    if (!file) return;

    setFiles([file]);
    setUploading(true);

    try {
      // 1. Request SAS URL and request ID
      const res = await fetch(`${import.meta.env.VITE_API_BASE}/getUploadUrl`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: file.name })
      });
      if (!res.ok) throw new Error('Failed to obtain upload URL');
      const { id, uploadUrl } = await res.json();

      // 2. Upload file via PUT to SAS URL
      const putRes = await fetch(uploadUrl, {
        method: 'PUT',
        headers: { 'x-ms-blob-type': 'BlockBlob' },
        body: file
      });
      if (!putRes.ok) throw new Error('Upload failed');

      // 3. Poll status endpoint
      const poll = async (retries = 20) => {
        const statusRes = await fetch(`${import.meta.env.VITE_API_BASE}/status/${id}`);
        if (statusRes.status === 404 && retries) {
          return setTimeout(() => poll(retries - 1), 3000);
        }
        if (!statusRes.ok) throw new Error('Status check failed');
        const metadata = await statusRes.json();
        setMeta(metadata);
        setUploading(false);
      };
      poll();
    } catch (err) {
      console.error(err);
      alert(err.message);
      setUploading(false);
    }
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { 'application/pdf': ['.pdf'], 'application/msword': ['.doc', '.docx'] }
  });

  return (
    <section className="container" style={{ width: '400px' }}>
      <div {...getRootProps({ style: baseStyle })}>
        <input {...getInputProps()} />
        {isDragActive ? <p>Drop the files here ...</p> : <p>Drag & drop a manuscript here, or click to select files</p>}
      </div>
      <aside style={{ marginTop: '1rem', color: '#ff6f00' }}>
        {uploading && <p>Uploading & processing…</p>}
        {files.map((file) => (
          <p key={file.name}>{file.name} - {file.size} bytes</p>
        ))}
        {meta && (
          <pre style={{ whiteSpace: 'pre-wrap', wordWrap: 'break-word', background: '#222', padding: '1rem', borderRadius: 4, color: '#fff' }}>
            {JSON.stringify(meta, null, 2)}
          </pre>
        )}
      </aside>
    </section>
  );
}

export default UploadDropzone;
