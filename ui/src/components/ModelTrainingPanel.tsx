import { useEffect, useRef, useState } from "react";
import { AlertTriangle, ChevronDown, ChevronUp, RefreshCw, Upload } from "lucide-react";
import type { ModelStatus, RetrainResult } from "../types";
import { type RegressionDetail, RegressionBlockedError, getModelStatus, retrainModels, uploadTrainingData } from "../lib/api";

function fmtDate(iso?: string): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  } catch {
    return iso;
  }
}

function AucCell({ val }: { val?: number }) {
  if (val === undefined || val === null) return <span style={{ color: "rgba(255,255,255,0.3)" }}>—</span>;
  const pct = (val * 100).toFixed(1);
  const color = val >= 0.85 ? "#d5fa54" : val >= 0.75 ? "#5170ff" : "#ff66c4";
  return <span style={{ color, fontWeight: 600 }}>{pct}%</span>;
}

export default function ModelTrainingPanel() {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<ModelStatus | null>(null);
  const [loadingStatus, setLoadingStatus] = useState(false);
  const [retraining, setRetraining] = useState(false);
  const [retrainResult, setRetrainResult] = useState<RetrainResult | null>(null);
  const [retrainError, setRetrainError] = useState<string | null>(null);
  const [regressionBlocked, setRegressionBlocked] = useState<RegressionDetail | null>(null);
  const [uploadMsg, setUploadMsg] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  function loadStatus() {
    setLoadingStatus(true);
    getModelStatus()
      .then(setStatus)
      .catch(() => {})
      .finally(() => setLoadingStatus(false));
  }

  useEffect(() => {
    if (open && !status) loadStatus();
  }, [open]);

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadMsg(null);
    setUploadError(null);
    try {
      const res = await uploadTrainingData(file);
      setUploadMsg(`Added ${res.records_added} records — total: ${res.total_records}`);
      loadStatus();
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Upload failed");
    }
    // reset file input
    if (fileRef.current) fileRef.current.value = "";
  }

  async function handleRetrain(force = false) {
    setRetraining(true);
    setRetrainResult(null);
    setRetrainError(null);
    setRegressionBlocked(null);
    try {
      const res = await retrainModels(force);
      setRetrainResult(res);
      loadStatus();
    } catch (err) {
      if (err instanceof RegressionBlockedError) {
        setRegressionBlocked(err.regression);
      } else {
        setRetrainError(err instanceof Error ? err.message : "Retraining failed");
      }
    }
    setRetraining(false);
  }

  const prevLogistic = status?.models?.logistic?.auc;
  const prevGbt = status?.models?.gbt?.auc;

  return (
    <div
      className="flex-none rounded-xl border"
      style={{ background: "#111214", borderColor: "rgba(255,255,255,0.08)" }}
    >
      {/* Header toggle */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-5 py-3 text-left"
      >
        <span className="text-xs font-semibold" style={{ color: "rgba(255,255,255,0.6)" }}>
          Model Training
        </span>
        {open ? (
          <ChevronUp className="h-3.5 w-3.5" style={{ color: "rgba(255,255,255,0.3)" }} />
        ) : (
          <ChevronDown className="h-3.5 w-3.5" style={{ color: "rgba(255,255,255,0.3)" }} />
        )}
      </button>

      {open && (
        <div className="border-t px-5 pb-5 pt-4 space-y-4" style={{ borderColor: "rgba(255,255,255,0.07)" }}>
          {loadingStatus && (
            <p className="text-xs" style={{ color: "rgba(255,255,255,0.35)" }}>Loading status…</p>
          )}

          {status && (
            <>
              {/* Status row */}
              <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs" style={{ color: "rgba(255,255,255,0.45)" }}>
                <span>Training records: <span className="text-white font-medium">{status.training_data_count}</span></span>
                <span>Feedback records: <span className="text-white font-medium">{status.feedback_count}</span></span>
                <span>Last trained: <span className="text-white font-medium">{fmtDate(status.trained_at)}</span></span>
              </div>

              {/* Metrics table */}
              {(status.models?.logistic || status.models?.gbt) && (
                <div className="overflow-hidden rounded-lg border" style={{ borderColor: "rgba(255,255,255,0.08)" }}>
                  <table className="w-full text-xs">
                    <thead>
                      <tr style={{ background: "rgba(255,255,255,0.04)", borderBottom: "1px solid rgba(255,255,255,0.07)" }}>
                        <th className="px-3 py-2 text-left font-medium" style={{ color: "rgba(255,255,255,0.35)" }}>Model</th>
                        <th className="px-3 py-2 text-right font-medium" style={{ color: "rgba(255,255,255,0.35)" }}>Test AUC</th>
                        <th className="px-3 py-2 text-right font-medium" style={{ color: "rgba(255,255,255,0.35)" }}>CV AUC</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr className="border-t" style={{ borderColor: "rgba(255,255,255,0.05)" }}>
                        <td className="px-3 py-2" style={{ color: "rgba(255,255,255,0.5)" }}>Logistic</td>
                        <td className="px-3 py-2 text-right"><AucCell val={status.models?.logistic?.auc} /></td>
                        <td className="px-3 py-2 text-right"><AucCell val={status.models?.logistic?.cv_auc} /></td>
                      </tr>
                      <tr className="border-t" style={{ borderColor: "rgba(255,255,255,0.05)" }}>
                        <td className="px-3 py-2" style={{ color: "rgba(255,255,255,0.5)" }}>GBT</td>
                        <td className="px-3 py-2 text-right"><AucCell val={status.models?.gbt?.auc} /></td>
                        <td className="px-3 py-2 text-right"><AucCell val={status.models?.gbt?.cv_auc} /></td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}

          {/* Upload training data */}
          <div>
            <p className="mb-2 text-[10px] font-semibold uppercase tracking-widest" style={{ color: "rgba(255,255,255,0.3)" }}>
              Upload training data
            </p>
            <label
              className="flex items-center gap-2 cursor-pointer rounded-lg px-3 py-2 text-xs transition-colors"
              style={{ background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.08)", color: "rgba(255,255,255,0.5)" }}
              onMouseEnter={(e) => (e.currentTarget.style.borderColor = "rgba(213,250,84,0.3)")}
              onMouseLeave={(e) => (e.currentTarget.style.borderColor = "rgba(255,255,255,0.08)")}
            >
              <Upload className="h-3.5 w-3.5 shrink-0" />
              <span>Choose .csv or .json file</span>
              <input
                ref={fileRef}
                type="file"
                accept=".csv,.json"
                className="hidden"
                onChange={handleUpload}
              />
            </label>
            {uploadMsg && (
              <p className="mt-1.5 text-xs" style={{ color: "#d5fa54" }}>{uploadMsg}</p>
            )}
            {uploadError && (
              <p className="mt-1.5 text-xs text-red-400">{uploadError}</p>
            )}
          </div>

          {/* Retrain */}
          <div>
            <button
              onClick={() => handleRetrain(false)}
              disabled={retraining}
              className="flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium transition-colors disabled:opacity-50"
              style={{ background: "rgba(81,112,255,0.12)", color: "#5170ff", border: "1px solid rgba(81,112,255,0.25)" }}
              onMouseEnter={(e) => { if (!retraining) (e.currentTarget as HTMLElement).style.background = "rgba(81,112,255,0.2)"; }}
              onMouseLeave={(e) => (e.currentTarget as HTMLElement).style.background = "rgba(81,112,255,0.12)"}
            >
              <RefreshCw className={`h-3.5 w-3.5 ${retraining ? "animate-spin" : ""}`} />
              {retraining ? "Retraining…" : "Retrain models"}
            </button>

            {retrainError && (
              <p className="mt-2 text-xs text-red-400">{retrainError}</p>
            )}

            {regressionBlocked && (
              <div
                className="mt-3 rounded-lg border px-3 py-2.5 space-y-2"
                style={{ background: "rgba(217,119,6,0.08)", borderColor: "rgba(217,119,6,0.2)" }}
              >
                <div className="flex items-center gap-1.5">
                  <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-amber-400" />
                  <p className="text-xs font-medium text-amber-400">Regression detected — retrain blocked</p>
                </div>
                <div className="space-y-1">
                  {(["logistic", "gbt"] as const).map((m) => {
                    const d = regressionBlocked[m];
                    const delta = d.new_auc - d.old_auc;
                    return (
                      <div key={m} className="flex items-center gap-2 text-xs" style={{ color: "rgba(255,255,255,0.5)" }}>
                        <span className="w-14">{m === "logistic" ? "Logistic" : "GBT"}</span>
                        <span style={{ color: "rgba(255,255,255,0.35)" }}>{(d.old_auc * 100).toFixed(1)}%</span>
                        <span style={{ color: "rgba(255,255,255,0.25)" }}>→</span>
                        <span style={{ color: "#ff66c4", fontWeight: 600 }}>{(d.new_auc * 100).toFixed(1)}%</span>
                        <span style={{ color: "#ff66c4" }}>({(delta * 100).toFixed(3)})</span>
                      </div>
                    );
                  })}
                </div>
                <button
                  onClick={() => handleRetrain(true)}
                  disabled={retraining}
                  className="flex items-center gap-1.5 rounded px-2.5 py-1.5 text-xs font-medium disabled:opacity-50"
                  style={{ background: "rgba(217,119,6,0.15)", color: "#f59e0b", border: "1px solid rgba(217,119,6,0.3)" }}
                >
                  <RefreshCw className={`h-3 w-3 ${retraining ? "animate-spin" : ""}`} />
                  Force retrain anyway
                </button>
              </div>
            )}

            {retrainResult && (
              <div className="mt-3 space-y-1.5">
                <p className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: "rgba(255,255,255,0.3)" }}>
                  Retrain complete · {retrainResult.total_records} records
                </p>
                {/* Before/after AUC comparison */}
                {[
                  { label: "Logistic", prev: prevLogistic, next: retrainResult.logistic.auc },
                  { label: "GBT", prev: prevGbt, next: retrainResult.gbt.auc },
                ].map(({ label, prev, next }) => {
                  const delta = prev !== undefined ? next - prev : null;
                  const deltaStr = delta !== null
                    ? `${delta >= 0 ? "+" : ""}${(delta * 100).toFixed(3)}`
                    : null;
                  const deltaColor = delta !== null ? (delta >= 0 ? "#d5fa54" : "#ff66c4") : undefined;
                  return (
                    <div key={label} className="flex items-center gap-2 text-xs" style={{ color: "rgba(255,255,255,0.5)" }}>
                      <span className="w-14">{label}</span>
                      {prev !== undefined && (
                        <span style={{ color: "rgba(255,255,255,0.35)" }}>{(prev * 100).toFixed(1)}%</span>
                      )}
                      {prev !== undefined && <span style={{ color: "rgba(255,255,255,0.25)" }}>→</span>}
                      <span style={{ color: "#d5fa54", fontWeight: 600 }}>{(next * 100).toFixed(1)}%</span>
                      {deltaStr && (
                        <span style={{ color: deltaColor }}>({deltaStr})</span>
                      )}
                    </div>
                  );
                })}
                <p className="text-[10px]" style={{ color: "rgba(255,255,255,0.3)" }}>
                  Models reloaded — new scores will apply on next pipeline run
                </p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
