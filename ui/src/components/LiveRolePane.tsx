import type { LiveCoarseBrief, LiveRubricUsed } from "../types";

const FLEX_STYLE: Record<string, { fg: string; label: string }> = {
  rigid: { fg: "rgba(255,255,255,0.4)", label: "Rigid" },
  some_flex: { fg: "#eab86b", label: "Some flex" },
  likely_flexible: { fg: "#d5fa54", label: "Likely flexible" },
};

interface LiveRolePaneProps {
  job: { id: string; title: string; company: string; required_skills: string[]; preferred_skills: string[] };
  coarseBrief: LiveCoarseBrief;
  rubricUsed?: LiveRubricUsed | null;
  stats: {
    candidatesConsidered: number;
    candidatesIndexed: number;
    candidatesPassedFilter: number;
    candidatesReranked: number;
    eliminatedCount: number;
  };
}

export default function LiveRolePane({ job, coarseBrief, rubricUsed, stats }: LiveRolePaneProps) {
  // Persisted runs saved before required_skills/preferred_skills were added to
  // the job payload won't have these fields — default so old runs still load
  // instead of crashing (data/live_runs/*.json is old-code output, a real
  // boundary the current code can't assume matches its own current shape).
  const requiredSkills = job.required_skills ?? [];
  const preferredSkills = job.preferred_skills ?? [];

  return (
    <div
      className="flex w-full flex-none flex-col gap-5 lg:w-[340px] lg:border-r lg:pr-5"
      style={{ borderColor: "rgba(255,255,255,0.08)" }}
    >
      <div>
        <p className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: "rgba(255,255,255,0.3)" }}>
          {job.company}
        </p>
        <h2 className="text-lg font-semibold text-white">{job.title}</h2>
        <p className="mt-2 text-sm" style={{ color: "rgba(255,255,255,0.55)" }}>{coarseBrief.summary}</p>

        {(requiredSkills.length > 0 || preferredSkills.length > 0) && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {requiredSkills.map((s) => (
              <span
                key={`req-${s}`}
                className="rounded px-2 py-0.5 text-[11px] font-medium"
                style={{ background: "rgba(213,250,84,0.1)", color: "#d5fa54" }}
              >
                {s}
              </span>
            ))}
            {preferredSkills.map((s) => (
              <span
                key={`pref-${s}`}
                className="rounded px-2 py-0.5 text-[11px]"
                style={{ background: "rgba(255,255,255,0.05)", color: "rgba(255,255,255,0.45)" }}
              >
                {s}
              </span>
            ))}
          </div>
        )}
      </div>

      <div className="flex flex-wrap gap-2 text-[11px]" style={{ color: "rgba(255,255,255,0.4)" }}>
        <span className="rounded px-2 py-1" style={{ background: "rgba(255,255,255,0.05)" }}>
          {stats.candidatesConsidered} of {stats.candidatesIndexed} scanned
        </span>
        <span className="rounded px-2 py-1" style={{ background: "rgba(255,255,255,0.05)" }}>
          {stats.candidatesPassedFilter} passed filter
        </span>
        <span className="rounded px-2 py-1" style={{ background: "rgba(255,255,255,0.05)" }}>
          {stats.eliminatedCount} eliminated
        </span>
        <span className="rounded px-2 py-1" style={{ background: "rgba(255,255,255,0.05)" }}>
          {stats.candidatesReranked} reranked
        </span>
        <span className="rounded px-2 py-1" style={{ background: "rgba(255,255,255,0.05)" }}>
          UK-based required: {coarseBrief.requires_uk_based}
        </span>
        <span className="rounded px-2 py-1" style={{ background: "rgba(255,255,255,0.05)" }}>
          Sponsors visa: {coarseBrief.offers_visa_sponsorship}
        </span>
        <span
          className="rounded px-2 py-1"
          style={
            rubricUsed
              ? { background: "rgba(213,250,84,0.1)", color: "#d5fa54" }
              : { background: "rgba(255,255,255,0.05)" }
          }
          title={
            rubricUsed
              ? `${rubricUsed.rubric_id} v${rubricUsed.version} (${rubricUsed.role_specific ? "role-specific" : "global template"}), ${rubricUsed.signal_count} signals`
              : "No Mind rubric found for this role — fine-rerank used generic required/preferred-skills criteria"
          }
        >
          {rubricUsed
            ? `Rubric: ${rubricUsed.rubric_id} (${rubricUsed.signal_count} signals)`
            : "Rubric: none (generic criteria)"}
        </span>
      </div>

      {coarseBrief.flexibility_notes.length > 0 && (
        <div className="rounded-lg border p-3" style={{ borderColor: "rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.02)" }}>
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-widest" style={{ color: "rgba(255,255,255,0.3)" }}>
            Constraint flexibility judgment
          </p>
          <div className="flex flex-col gap-1.5">
            {coarseBrief.flexibility_notes.map((n, i) => (
              <div key={i} className="flex items-start gap-2 text-xs">
                <span
                  className="mt-0.5 shrink-0 rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide"
                  style={{ color: FLEX_STYLE[n.flex_judgment]?.fg ?? "rgba(255,255,255,0.4)", background: "rgba(255,255,255,0.05)" }}
                >
                  {FLEX_STYLE[n.flex_judgment]?.label ?? n.flex_judgment}
                </span>
                <span style={{ color: "rgba(255,255,255,0.5)" }}>{n.constraint_description}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
