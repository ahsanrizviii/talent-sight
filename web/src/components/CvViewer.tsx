import { useEffect, useState } from "react";
import { apiBlob } from "../api";

// The original CV, shown next to what the AI read from it.
// PDFs are shown in the page. Browsers cannot show DOCX files, so for those
// the text read from the file is shown, and the file can be downloaded.
export default function CvViewer({
  candidateId,
  filename,
  text,
}: {
  candidateId: number;
  filename: string;
  text: string;
}) {
  const isPdf = filename.toLowerCase().endsWith(".pdf");
  const [pdfUrl, setPdfUrl] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!isPdf) return;
    let url = "";
    apiBlob(`/candidates/${candidateId}/cv`)
      .then((blob) => {
        url = URL.createObjectURL(blob);
        setPdfUrl(url);
      })
      .catch((err) => setError(err.message));
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [candidateId, isPdf]);

  async function download() {
    try {
      const blob = await apiBlob(`/candidates/${candidateId}/cv`);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <h2>Original CV</h2>
          <p className="muted small">{filename}</p>
        </div>
        <button className="button secondary" type="button" onClick={download}>
          Download
        </button>
      </div>

      {error && <p className="error">{error}</p>}

      {isPdf ? (
        pdfUrl ? (
          <iframe className="cv-frame" src={pdfUrl} title={`CV: ${filename}`} />
        ) : (
          !error && <p className="muted">Loading the CV...</p>
        )
      ) : (
        <>
          <p className="muted small">
            Browsers cannot show DOCX files. This is the text read from the file.
          </p>
          <pre className="cv-text">{text || "No text could be read from this file."}</pre>
        </>
      )}
    </div>
  );
}