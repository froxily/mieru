import { useCallback, useRef, useState, type DragEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, getJson, uploadFile } from "../../api/client";
import type { DatasetMeta } from "../../api/datasetTypes";
import { Card } from "../../components/Card";
import { PageHeader, SectionTitle } from "../../components/PageHeader";
import { Callout } from "../../components/States";
import { IconCheck, IconFile, IconShield, IconSparkle, IconUpload } from "../../components/icons";
import { useDatasetList } from "../../features/datasets/useDatasets";
import { formatNumber } from "../../lib/format";

interface HealthLimits {
  environment?: string;
  limits: { max_upload_mb: number; max_upload_rows: number; dataset_ttl_minutes: number; accepted_extensions: string[] };
}

const ACCEPT = ".csv,.tsv,.txt,.xlsx";
const SAMPLE_URL = "/samples/mieru-sample-retail-orders-synthetic.csv";
const SAMPLE_XLSX_URL = "/samples/mieru-sample-retail-orders-synthetic-ja.xlsx";

const DETECTION_STEPS = [
  { title: "Reads messy files", text: "CSV, TSV or Excel; UTF-8, Shift_JIS/CP932 or Latin encodings; title rows and multiple sheets." },
  {
    title: "Understands your columns",
    text: "Recognises orders, dates, products, prices, quantities, discounts, costs and status in English, Japanese, Portuguese or Spanish.",
  },
  { title: "Counts revenue once", text: "Detects order vs line-item files so order totals repeated on every line are never double counted." },
  {
    title: "Cleans transparently",
    text: "Duplicates, cancellations, returns and unreadable values are flagged with their impact; your file is never modified.",
  },
];

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function UploadPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [selected, setSelected] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const health = useQuery({ queryKey: ["health"], queryFn: ({ signal }) => getJson<HealthLimits>("/api/health", signal), staleTime: Infinity });
  const datasets = useDatasetList();
  const limits = health.data?.limits;

  const startUpload = useCallback(
    async (file: File) => {
      setError(null);
      setSelected(file);
      const extension = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
      if (!ACCEPT.split(",").includes(extension)) {
        setError("Unsupported file type. Upload a CSV, TSV, TXT or XLSX file.");
        return;
      }
      if (limits && file.size > limits.max_upload_mb * 1024 * 1024) {
        setError(`This file is ${formatBytes(file.size)}; the limit is ${limits.max_upload_mb} MB.`);
        return;
      }
      setProgress(0);
      try {
        const meta = await uploadFile<DatasetMeta>("/api/datasets", file, setProgress);
        await queryClient.invalidateQueries({ queryKey: ["datasets"] });
        navigate(`/data/${meta.dataset_id}`);
      } catch (caught) {
        setProgress(null);
        setError(caught instanceof ApiError ? caught.message : "Upload failed. Please try again.");
      }
    },
    [limits, navigate, queryClient],
  );

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files?.[0];
    if (file) void startUpload(file);
  };

  const uploading = progress !== null;
  return (
    <div className="page">
      <PageHeader
        eyebrow="Your data"
        title="Turn a sales spreadsheet into a dashboard"
        description="Drop a CSV or Excel export from your shop, marketplace or POS. MIERU detects the structure, cleans it conservatively and builds dashboards automatically: no forms, no mapping wizard."
      />

      <div
        className={`dropzone${dragging ? " dragging" : ""}`}
        role="button"
        tabIndex={0}
        aria-label="Upload a spreadsheet: drop a file here or press Enter to choose one"
        onClick={() => !uploading && inputRef.current?.click()}
        onKeyDown={(event) => {
          if ((event.key === "Enter" || event.key === " ") && !uploading) {
            event.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(event) => {
          event.preventDefault();
          if (!uploading) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT}
          className="visually-hidden"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void startUpload(file);
            event.target.value = "";
          }}
        />
        <div className="dropzone-icon">{uploading ? <IconFile /> : <IconUpload />}</div>
        {uploading && selected ? (
          <div className="stack" style={{ width: "min(420px, 100%)", alignItems: "center" }}>
            <strong>{selected.name}</strong>
            <span className="text-sm muted">
              {progress !== null && progress < 1 ? `Uploading… ${Math.round(progress * 100)}%` : "Upload complete, starting analysis…"}
            </span>
            <div className="progress" style={{ width: "100%" }} aria-hidden="true">
              <div
                className={`progress-bar${progress !== null && progress >= 1 ? " indeterminate" : ""}`}
                style={{ width: `${Math.round((progress ?? 0) * 100)}%` }}
              />
            </div>
          </div>
        ) : (
          <>
            <div style={{ fontSize: "1.125rem", fontWeight: 600, color: "var(--ink-1)" }}>Drop your file here, or click to browse</div>
            <div className="text-sm muted">
              CSV · TSV · TXT · XLSX{limits ? ` · up to ${limits.max_upload_mb} MB and ${formatNumber(limits.max_upload_rows)} rows` : ""}
            </div>
            <button
              type="button"
              className="btn btn-primary"
              style={{ marginTop: 8 }}
              onClick={(event) => {
                event.stopPropagation();
                inputRef.current?.click();
              }}
            >
              Choose a file
            </button>
          </>
        )}
      </div>

      <p className="visually-hidden" aria-live="polite">
        {error
          ? `Upload failed: ${error}`
          : uploading && selected
            ? progress !== null && progress >= 1
              ? `${selected.name} uploaded. Starting analysis.`
              : `Uploading ${selected.name}.`
            : ""}
      </p>
      {error && (
        <Callout tone="critical" title="This file could not be uploaded">
          {error}
        </Callout>
      )}

      <div className="row row-wrap" style={{ justifyContent: "space-between" }}>
        <span className="text-sm muted">
          <IconShield width={14} height={14} style={{ verticalAlign: "-2px", marginRight: 6 }} />
          Files stay private to this browser session and are deleted automatically after {limits?.dataset_ttl_minutes ?? 120} minutes. Your original file is
          never modified.
          {health.data?.environment === "production" &&
            " This public demo sleeps after a few idle minutes and keeps nothing on restart, so uploads can disappear sooner; keep your own copy of the file."}
        </span>
        <span className="row row-wrap" style={{ gap: 8 }}>
          <a className="btn btn-sm" href={SAMPLE_URL} download>
            Download a synthetic sample file
          </a>
          <a className="btn btn-sm" href={SAMPLE_XLSX_URL} download>
            Same data as a Japanese Excel workbook
          </a>
        </span>
      </div>

      {datasets.data && datasets.data.datasets.length > 0 && (
        <>
          <SectionTitle title="Your recent uploads" description="Available until they expire" />
          <div className="grid grid-kpi">
            {datasets.data.datasets.map((dataset, index) => (
              <Card key={dataset.dataset_id} interactive stagger={index}>
                <button
                  type="button"
                  className="stack"
                  style={{ gap: 6, background: "none", border: 0, padding: 0, textAlign: "left", cursor: "pointer", width: "100%" }}
                  onClick={() => navigate(`/data/${dataset.dataset_id}`)}
                >
                  <span className="row" style={{ gap: 8 }}>
                    <IconFile width={16} height={16} />
                    <strong style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{dataset.display_name}</strong>
                  </span>
                  <span className="text-xs muted">
                    Uploaded {new Date(dataset.created_at).toLocaleTimeString()} · expires {new Date(dataset.expires_at).toLocaleTimeString()}
                  </span>
                  <span
                    className={`badge ${dataset.status === "ready" ? "badge-good" : dataset.status === "failed" ? "badge-critical" : "badge-accent"}`}
                    style={{ alignSelf: "flex-start" }}
                  >
                    {dataset.status === "ready" ? "Ready" : dataset.status === "failed" ? "Failed" : "Processing"}
                  </span>
                </button>
              </Card>
            ))}
          </div>
        </>
      )}

      <SectionTitle title="What happens after you upload" description="Everything below runs automatically." />
      <div className="grid grid-kpi">
        {DETECTION_STEPS.map((step, index) => (
          <Card key={step.title} stagger={index}>
            <div className="stack" style={{ gap: 8 }}>
              <span className="state-icon" style={{ width: 36, height: 36, background: "var(--accent-soft)", color: "var(--accent-strong)" }}>
                {index === 3 ? <IconCheck width={18} height={18} /> : <IconSparkle width={18} height={18} />}
              </span>
              <strong>{step.title}</strong>
              <span className="text-sm muted">{step.text}</span>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
