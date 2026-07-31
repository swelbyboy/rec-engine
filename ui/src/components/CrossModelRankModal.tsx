import { X } from "lucide-react";
import type { RankSource } from "../types";

/** Modal shown when clicking a candidate card in the Compare tab — shows
 * where that candidate landed across every currently-loaded model column
 * (rec-engine PoC / Mind Live / Mind Fixed / future LLM-only), so the same
 * person's placement can be compared at a glance instead of scrolling three
 * columns side by side. Sourced entirely from what's already loaded in each
 * column (see ComparePanel's onRankedChange) — no extra API calls, and
 * scoped to whatever run is currently selected per column, not a search
 * across every historical run. */
export default function CrossModelRankModal({
  candidateId,
  candidateName,
  sources,
  onClose,
}: {
  candidateId: string;
  candidateName: string;
  sources: RankSource[];
  onClose: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(0,0,0,0.6)" }}
      onClick={onClose}
    >
      <div
        className="w-full max-w-sm rounded-xl border p-4"
        style={{ borderColor: "rgba(255,255,255,0.1)", background: "#111214" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-2">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: "rgba(255,255,255,0.3)" }}>
              Rank across models
            </p>
            <p className="mt-0.5 text-sm font-medium text-white">{candidateName}</p>
            <p className="text-[11px]" style={{ color: "rgba(255,255,255,0.35)" }}>BH #{candidateId}</p>
          </div>
          <button onClick={onClose} className="rounded p-1" style={{ color: "rgba(255,255,255,0.4)" }}>
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="mt-3 flex flex-col gap-1.5">
          {sources.map((s) => {
            const rank = s.rankByCandidateId[candidateId];
            return (
              <div
                key={s.label}
                className="flex items-center justify-between rounded-md px-2.5 py-1.5 text-xs"
                style={{ background: "rgba(255,255,255,0.03)" }}
              >
                <span style={{ color: "rgba(255,255,255,0.6)" }}>{s.label}</span>
                {rank != null ? (
                  <span className="font-mono font-medium" style={{ color: "#d5fa54" }}>
                    {rank}/{s.total}
                  </span>
                ) : (
                  <span className="text-[11px]" style={{ color: "rgba(255,255,255,0.3)" }}>
                    Not ranked in this run
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
