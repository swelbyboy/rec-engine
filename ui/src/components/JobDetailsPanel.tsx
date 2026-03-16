import type { JobDetails } from "../types";

interface Props {
  title: string;
  details: JobDetails;
}

function Pill({ label, soft }: { label: string; soft?: boolean }) {
  return (
    <span
      className="inline-flex items-center rounded px-2 py-0.5 text-xs"
      style={
        soft
          ? { background: "rgba(255,255,255,0.05)", color: "rgba(255,255,255,0.45)", border: "1px solid rgba(255,255,255,0.08)" }
          : { background: "rgba(213,250,84,0.1)", color: "#d5fa54", border: "1px solid rgba(213,250,84,0.2)" }
      }
    >
      {label}
    </span>
  );
}

export default function JobDetailsPanel({ title, details }: Props) {
  const hardConstraints = details.constraints.filter((c) => c.type === "hard");
  const softConstraints = details.constraints.filter((c) => c.type === "soft");

  return (
    <div className="flex flex-col gap-5 overflow-y-auto">
      {/* Job heading */}
      <div>
        <p className="text-[10px] font-semibold uppercase tracking-widest mb-1" style={{ color: "rgba(255,255,255,0.3)" }}>
          Role extracted
        </p>
        <p className="text-sm font-semibold text-white">{title}</p>
        <p className="text-xs mt-0.5" style={{ color: "rgba(255,255,255,0.45)" }}>
          {details.company} · {details.seniority} · {details.min_years_experience}+ yrs
          {details.management_required && " · management required"}
        </p>
      </div>

      {/* Required skills */}
      {details.required_skills.length > 0 && (
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-widest mb-2" style={{ color: "rgba(255,255,255,0.3)" }}>
            Required skills
          </p>
          <div className="flex flex-wrap gap-1.5">
            {details.required_skills.map((s) => <Pill key={s} label={s} />)}
          </div>
        </div>
      )}

      {/* Preferred skills */}
      {details.preferred_skills.length > 0 && (
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-widest mb-2" style={{ color: "rgba(255,255,255,0.3)" }}>
            Preferred skills
          </p>
          <div className="flex flex-wrap gap-1.5">
            {details.preferred_skills.map((s) => <Pill key={s} label={s} soft />)}
          </div>
        </div>
      )}

      {/* Hard constraints */}
      {hardConstraints.length > 0 && (
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-widest mb-2" style={{ color: "rgba(255,255,255,0.3)" }}>
            Hard requirements
          </p>
          <ul className="space-y-1.5">
            {hardConstraints.map((c, i) => (
              <li key={i} className="flex items-start gap-2 text-xs" style={{ color: "rgba(255,255,255,0.6)" }}>
                <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: "#ff66c4" }} />
                {c.description}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Soft constraints / preferences */}
      {softConstraints.length > 0 && (
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-widest mb-2" style={{ color: "rgba(255,255,255,0.3)" }}>
            Preferences
          </p>
          <ul className="space-y-1.5">
            {softConstraints.map((c, i) => (
              <li key={i} className="flex items-start gap-2 text-xs" style={{ color: "rgba(255,255,255,0.45)" }}>
                <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: "rgba(255,255,255,0.2)" }} />
                {c.description}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
