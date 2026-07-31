import { useState } from "react";
import { ChevronDown, ChevronUp, FileDown, Linkedin, Loader2 } from "lucide-react";
import type { LiveRankedCandidate, LiveVerdict } from "../types";

const VERDICT_STYLE: Record<LiveVerdict, { bg: string; fg: string; label: string }> = {
  strong_match: { bg: "rgba(213,250,84,0.14)", fg: "#d5fa54", label: "Strong match" },
  good_match: { bg: "rgba(81,112,255,0.14)", fg: "#8ea1ff", label: "Good match" },
  possible: { bg: "rgba(217,119,6,0.14)", fg: "#eab86b", label: "Possible" },
  weak_match: { bg: "rgba(255,255,255,0.06)", fg: "rgba(255,255,255,0.45)", label: "Weak match" },
};

export function VerdictBadge({ verdict }: { verdict: LiveVerdict }) {
  const s = VERDICT_STYLE[verdict];
  return (
    <span
      className="inline-flex shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
      style={{ background: s.bg, color: s.fg }}
    >
      {s.label}
    </span>
  );
}

export function ExpandableSection({ label, text }: { label: string; text: string | undefined }) {
  const [open, setOpen] = useState(false);
  if (!text?.trim()) return null;
  return (
    <div className="mt-2">
      <button
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide transition-colors"
        style={{ color: "rgba(255,255,255,0.35)" }}
      >
        {open ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
        {label}
      </button>
      {open && (
        <p className="mt-1 whitespace-pre-line text-[11px]" style={{ color: "rgba(255,255,255,0.45)" }}>
          {text}
        </p>
      )}
    </div>
  );
}

type DownloadState = "idle" | "loading" | "error";

export function DownloadCvButton({ bullhornId }: { bullhornId: string }) {
  const [state, setState] = useState<DownloadState>("idle");

  async function handleDownload() {
    setState("loading");
    try {
      const res = await fetch(`/api/live/candidates/${bullhornId}/cv`);
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(body.detail ?? `HTTP ${res.status}`);
      }
      const blob = await res.blob();
      const disposition = res.headers.get("content-disposition") ?? "";
      const filenameMatch = disposition.match(/filename="?([^"]+)"?/);
      const filename = filenameMatch?.[1] ?? `cv-${bullhornId}`;

      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
      setState("idle");
    } catch {
      setState("error");
      setTimeout(() => setState("idle"), 4000);
    }
  }

  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        handleDownload();
      }}
      disabled={state === "loading"}
      className="flex items-center gap-1 underline underline-offset-2 disabled:opacity-60"
      style={{ color: state === "error" ? "#f87171" : "#8ea1ff" }}
    >
      {state === "loading" ? (
        <Loader2 className="h-3 w-3 animate-spin" />
      ) : (
        <FileDown className="h-3 w-3" />
      )}
      {state === "error" ? "CV unavailable" : "Download CV"}
    </button>
  );
}

export default function LiveCandidateCard({
  candidate,
  rank,
  onClick,
}: {
  candidate: LiveRankedCandidate;
  rank: number;
  onClick?: (candidateId: string, candidateName: string) => void;
}) {
  const c = candidate;
  // Older persisted runs predate matched_skills/missing_required_skills/
  // bullhorn_id/linkedin_url/cv_summary/call_notes — default so they still
  // render instead of crashing (see LiveRolePane for the same reasoning).
  const matchedSkills = c.matched_skills ?? [];
  const missingSkills = c.missing_required_skills ?? [];
  const bullhornId = c.bullhorn_id ?? "";
  return (
    <div
      className="rounded-lg border p-3"
      style={{
        borderColor: "rgba(255,255,255,0.08)",
        background: "#111214",
        cursor: onClick ? "pointer" : undefined,
      }}
      onClick={onClick ? () => onClick(c.candidate_id, c.name) : undefined}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono" style={{ color: "rgba(255,255,255,0.25)" }}>#{rank}</span>
          <span className="text-sm font-medium text-white">{c.name}</span>
          {c.flagged_for_review && (
            <span
              className="rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase"
              style={{ background: "rgba(217,119,6,0.14)", color: "#eab86b" }}
            >
              Flagged
            </span>
          )}
        </div>
        <VerdictBadge verdict={c.verdict} />
      </div>

      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]" style={{ color: "rgba(255,255,255,0.4)" }}>
        <span>{c.years_experience} yrs experience</span>
        <span className="capitalize">{c.seniority_level}</span>
        {bullhornId && <span>BH #{bullhornId}</span>}
        {c.linkedin_url && (
          <a
            href={c.linkedin_url}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="flex items-center gap-1 underline underline-offset-2"
            style={{ color: "#8ea1ff" }}
          >
            <Linkedin className="h-3 w-3" />
            LinkedIn
          </a>
        )}
        {bullhornId && <DownloadCvButton bullhornId={bullhornId} />}
      </div>

      <p className="mt-1.5 text-xs" style={{ color: "rgba(255,255,255,0.5)" }}>{c.rationale}</p>

      {(matchedSkills.length > 0 || missingSkills.length > 0) && (
        <div className="mt-2 flex flex-wrap gap-1">
          {matchedSkills.map((s) => (
            <span
              key={`matched-${s}`}
              className="rounded px-1.5 py-0.5 text-[10px]"
              style={{ background: "rgba(213,250,84,0.1)", color: "#d5fa54" }}
            >
              {s}
            </span>
          ))}
          {missingSkills.map((s) => (
            <span
              key={`missing-${s}`}
              className="rounded px-1.5 py-0.5 text-[10px] line-through"
              style={{ background: "rgba(255,255,255,0.05)", color: "rgba(255,255,255,0.35)" }}
            >
              {s}
            </span>
          ))}
        </div>
      )}

      <ExpandableSection label="CV summary" text={c.cv_summary} />
      <ExpandableSection label="Call notes" text={c.call_notes} />
    </div>
  );
}
