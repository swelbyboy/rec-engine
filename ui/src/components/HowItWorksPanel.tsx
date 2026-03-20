import { useEffect, useState } from "react";
import type { ModelMetrics, ModelWeights } from "../lib/api";
import { getModelMetrics, getModelWeights } from "../lib/api";

const FEATURE_LABELS: Record<string, string> = {
  required_skills_overlap: "Required skills overlap",
  preferred_skills_overlap: "Preferred skills overlap",
  industry_preferred_match: "Industry match",
  experience_delta: "Experience delta",
  seniority_match: "Seniority match",
  career_trajectory_score: "Career trajectory",
  interview_score: "Interview score",
  culture_fit_score: "Culture fit",
  management_match: "Management match",
  soft_constraint_score: "Constraint compliance",
};

const PIPELINE_STEPS = [
  {
    n: "01",
    label: "Parse JD",
    detail: "LLM extracts structured constraints, required/preferred skills, seniority, and experience thresholds from free-text.",
  },
  {
    n: "02",
    label: "Retrieve",
    detail: "Embed the job description and cosine-score all stored candidate embeddings. Return the top-K most semantically relevant candidates.",
  },
  {
    n: "03",
    label: "Constraint engine",
    detail: "Three-phase matching: canonical key → semantic similarity (threshold 0.75) → no-match. Hard mismatches eliminate candidates before scoring.",
  },
  {
    n: "04",
    label: "Score & rank",
    detail: "Feature vector (10 dimensions) fed into a default linear scorer, logistic regression, or gradient-boosted classifier. Eliminated candidates are set aside.",
  },
  {
    n: "05",
    label: "Explain",
    detail: "LLM generates a 2-paragraph natural-language assessment for each top-N candidate, referencing their feature scores and constraint matches.",
  },
];

// For logistic coefficients: normalise by max(|coef|) so bars are comparable
// positive = boosts shortlisting, negative = penalises
function normCoef(weights: number[]): number[] {
  const maxAbs = Math.max(...weights.map(Math.abs));
  return maxAbs === 0 ? weights : weights.map((w) => w / maxAbs);
}

// For GBT importances: already in [0,1] summing to 1; scale to max for visual comparison
function normImportance(weights: number[]): number[] {
  const max = Math.max(...weights);
  return max === 0 ? weights : weights.map((w) => w / max);
}

interface FeatureBarProps {
  label: string;
  raw: number;
  normalised: number;
  type: "coefficients" | "importances";
}

function FeatureBar({ label, raw, normalised, type }: FeatureBarProps) {
  const isCoef = type === "coefficients";
  const isNeg = isCoef && raw < 0;
  const barWidth = Math.abs(normalised) * 100;
  const barColor = isNeg ? "#ff66c4" : "#d5fa54";
  const rawLabel = isCoef
    ? `${raw >= 0 ? "+" : ""}${raw.toFixed(3)}`
    : `${(raw * 100).toFixed(1)}%`;

  return (
    <div className="flex items-center gap-3">
      <span className="w-44 shrink-0 text-xs text-right" style={{ color: "rgba(255,255,255,0.5)" }}>
        {label}
      </span>
      <div className="flex-1 flex items-center gap-2">
        {/* For coefficients, bar grows right from centre; for importances, left-aligned */}
        {isCoef ? (
          <div className="flex-1 flex items-center gap-1">
            {/* Negative side */}
            <div className="w-1/2 flex justify-end">
              {isNeg && (
                <div
                  className="h-1.5 rounded-full"
                  style={{ width: `${barWidth}%`, background: barColor }}
                />
              )}
            </div>
            {/* Centre line */}
            <div className="w-px h-3 shrink-0" style={{ background: "rgba(255,255,255,0.15)" }} />
            {/* Positive side */}
            <div className="w-1/2 flex justify-start">
              {!isNeg && (
                <div
                  className="h-1.5 rounded-full"
                  style={{ width: `${barWidth}%`, background: barColor }}
                />
              )}
            </div>
          </div>
        ) : (
          <div className="flex-1 h-1.5 overflow-hidden rounded-full" style={{ background: "rgba(255,255,255,0.07)" }}>
            <div className="h-full rounded-full" style={{ width: `${barWidth}%`, background: barColor }} />
          </div>
        )}
      </div>
      <span className="w-14 text-right text-xs font-mono" style={{ color: isNeg ? "#ff66c4" : "rgba(255,255,255,0.45)" }}>
        {rawLabel}
      </span>
    </div>
  );
}

// The legend row that only appears in the logistic card. Rendered invisible
// in the GBT card so both feature lists start at the same vertical position.
function LegendRow({ visible }: { visible: boolean }) {
  return (
    <div
      className="flex items-center justify-center gap-4 text-[10px]"
      style={{ color: "rgba(255,255,255,0.3)", visibility: visible ? "visible" : "hidden" }}
    >
      <span className="flex items-center gap-1.5">
        <span className="inline-block h-1.5 w-6 rounded-full" style={{ background: "#ff66c4" }} />
        reduces probability
      </span>
      <span className="flex items-center gap-1.5">
        <span className="inline-block h-1.5 w-6 rounded-full" style={{ background: "#d5fa54" }} />
        increases probability
      </span>
    </div>
  );
}

interface ModelCardProps {
  title: string;
  subtitle: string;
  weights: number[];
  featureNames: string[];
  type: "coefficients" | "importances";
  order: string[];
}

function ModelCard({ title, subtitle, weights, featureNames, type, order }: ModelCardProps) {
  const normalised = type === "coefficients" ? normCoef(weights) : normImportance(weights);
  const byName = Object.fromEntries(
    featureNames.map((name, i) => [name, { raw: weights[i], norm: normalised[i] }])
  );
  const sorted = order.map((name) => ({ name, ...(byName[name] ?? { raw: 0, norm: 0 }) }));

  return (
    <div
      className="rounded-xl border p-5 flex flex-col gap-4"
      style={{ background: "#111214", borderColor: "rgba(255,255,255,0.08)" }}
    >
      <div>
        <p className="text-sm font-semibold text-white">{title}</p>
        <p className="mt-0.5 text-xs" style={{ color: "rgba(255,255,255,0.4)" }}>{subtitle}</p>
      </div>

      {/* Always render legend row — hidden in GBT card so rows stay aligned */}
      <LegendRow visible={type === "coefficients"} />

      <div className="space-y-2.5">
        {sorted.map(({ name, raw, norm }) => (
          <FeatureBar
            key={name}
            label={FEATURE_LABELS[name] ?? name}
            raw={raw}
            normalised={norm}
            type={type}
          />
        ))}
      </div>

      {type === "coefficients" && (
        <p className="text-[10px]" style={{ color: "rgba(255,255,255,0.25)" }}>
          Coefficients are in the standardised feature space. Bars are scaled relative to the largest absolute coefficient.
        </p>
      )}
      {type === "importances" && (
        <p className="text-[10px]" style={{ color: "rgba(255,255,255,0.25)" }}>
          Feature importances sum to 1 across all features. Bars are scaled relative to the most important feature.
        </p>
      )}
    </div>
  );
}

export default function HowItWorksPanel() {
  const [weights, setWeights] = useState<ModelWeights | null>(null);
  const [metrics, setMetrics] = useState<ModelMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([getModelWeights(), getModelMetrics()])
      .then(([w, m]) => { setWeights(w); setMetrics(m); })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-8">
      {/* Pipeline steps */}
      <section>
        <p className="mb-4 text-[10px] font-semibold uppercase tracking-widest" style={{ color: "rgba(255,255,255,0.3)" }}>
          Pipeline
        </p>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
          {PIPELINE_STEPS.map((step) => (
            <div
              key={step.n}
              className="rounded-xl border p-4 flex flex-col gap-2"
              style={{ background: "#111214", borderColor: "rgba(255,255,255,0.08)" }}
            >
              <span className="text-[10px] font-bold" style={{ color: "rgba(255,255,255,0.2)" }}>
                {step.n}
              </span>
              <p className="text-sm font-semibold text-white">{step.label}</p>
              <p className="text-xs leading-relaxed" style={{ color: "rgba(255,255,255,0.4)" }}>
                {step.detail}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* Error metrics comparison */}
      <section>
        <p className="mb-4 text-[10px] font-semibold uppercase tracking-widest" style={{ color: "rgba(255,255,255,0.3)" }}>
          Model comparison · held-out test set{metrics ? ` (n=${metrics.n_test})` : ""}
        </p>

        {loading && (
          <div className="flex items-center gap-2 text-xs" style={{ color: "rgba(255,255,255,0.35)" }}>
            <div className="h-4 w-4 animate-spin rounded-full border-2" style={{ borderColor: "rgba(213,250,84,0.3)", borderTopColor: "transparent" }} />
            Computing metrics…
          </div>
        )}

        {metrics && (metrics.logistic || metrics.gbt) && (
          <div
            className="overflow-hidden rounded-xl border"
            style={{ background: "#111214", borderColor: "rgba(255,255,255,0.08)" }}
          >
            <table className="w-full text-xs">
              <thead>
                <tr style={{ background: "rgba(255,255,255,0.04)", borderBottom: "1px solid rgba(255,255,255,0.07)" }}>
                  <th className="px-4 py-3 text-left font-medium" style={{ color: "rgba(255,255,255,0.35)" }}>Metric</th>
                  <th className="px-4 py-3 text-right font-medium" style={{ color: "rgba(255,255,255,0.35)" }}>Logistic</th>
                  <th className="px-4 py-3 text-right font-medium" style={{ color: "rgba(255,255,255,0.35)" }}>GBT</th>
                  <th className="px-4 py-3 text-left font-medium" style={{ color: "rgba(255,255,255,0.35)" }}>Better</th>
                  <th className="px-4 py-3 text-left font-medium" style={{ color: "rgba(255,255,255,0.35)" }}>Note</th>
                </tr>
              </thead>
              <tbody>
                {[
                  {
                    label: "AUC-ROC",
                    log: metrics.logistic?.auc,
                    gbt: metrics.gbt?.auc,
                    fmt: (v: number) => v.toFixed(4),
                    higherIsBetter: true,
                    note: "Ranking quality — area under the ROC curve",
                  },
                  {
                    label: "Brier score (MSE)",
                    log: metrics.logistic?.brier_score,
                    gbt: metrics.gbt?.brier_score,
                    fmt: (v: number) => v.toFixed(4),
                    higherIsBetter: false,
                    note: "Mean squared error of predicted probabilities vs true labels",
                  },
                  {
                    label: "Log loss",
                    log: metrics.logistic?.log_loss,
                    gbt: metrics.gbt?.log_loss,
                    fmt: (v: number) => v.toFixed(4),
                    higherIsBetter: false,
                    note: "Cross-entropy loss — penalises overconfident wrong predictions",
                  },
                ].map(({ label, log, gbt, fmt, higherIsBetter, note }) => {
                  if (log === undefined || gbt === undefined) return null;
                  const logWins = higherIsBetter ? log > gbt : log < gbt;
                  const gbtWins = higherIsBetter ? gbt > log : gbt < log;
                  const cellStyle = (wins: boolean) => ({
                    color: wins ? "#d5fa54" : "rgba(255,255,255,0.55)",
                    fontWeight: wins ? 600 : 400,
                  });
                  return (
                    <tr key={label} className="border-t" style={{ borderColor: "rgba(255,255,255,0.05)" }}>
                      <td className="px-4 py-3 font-medium" style={{ color: "rgba(255,255,255,0.7)" }}>{label}</td>
                      <td className="px-4 py-3 text-right font-mono" style={cellStyle(logWins)}>{fmt(log)}</td>
                      <td className="px-4 py-3 text-right font-mono" style={cellStyle(gbtWins)}>{fmt(gbt)}</td>
                      <td className="px-4 py-3">
                        <span
                          className="rounded px-1.5 py-0.5 text-[10px] font-semibold"
                          style={{ background: "rgba(213,250,84,0.1)", color: "#d5fa54" }}
                        >
                          {gbtWins ? "GBT" : "Logistic"}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-[10px]" style={{ color: "rgba(255,255,255,0.3)" }}>{note}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <div className="px-4 py-3 border-t text-[10px] leading-relaxed" style={{ borderColor: "rgba(255,255,255,0.06)", color: "rgba(255,255,255,0.3)" }}>
              GBT wins on all metrics because the synthetic training data contains non-linear interactions (skill threshold cliff at 0.55, skill×seniority synergy, quadratic constraint gate) that logistic regression cannot model. Logistic is interpretable but less predictive on this data.
            </div>
          </div>
        )}
      </section>

      {/* Feature weights */}
      <section>
        <p className="mb-4 text-[10px] font-semibold uppercase tracking-widest" style={{ color: "rgba(255,255,255,0.3)" }}>
          Scoring model weights
        </p>

        {loading && (
          <div className="flex items-center gap-2 text-xs" style={{ color: "rgba(255,255,255,0.35)" }}>
            <div className="h-4 w-4 animate-spin rounded-full border-2" style={{ borderColor: "rgba(213,250,84,0.3)", borderTopColor: "transparent" }} />
            Loading model weights…
          </div>
        )}

        {error && (
          <p className="text-xs text-red-400">{error}</p>
        )}

        {weights && (
          (() => {
            // Shared row order: sort by GBT importance desc (most meaningful anchor).
            // Falls back to logistic |coef| if GBT unavailable, then canonical order.
            const names = weights.feature_names;
            const refWeights = weights.gbt?.weights ?? weights.logistic?.weights;
            const sharedOrder = refWeights
              ? [...names].sort((a, b) => {
                  const ai = names.indexOf(a), bi = names.indexOf(b);
                  return Math.abs(refWeights[bi]) - Math.abs(refWeights[ai]);
                })
              : names;

            return (
              <div className="grid gap-5 lg:grid-cols-2">
                {weights.logistic && (
                  <ModelCard
                    title="Logistic Regression"
                    subtitle="Linear decision boundary — learned feature weights with L2 regularisation. Each coefficient shows direction and magnitude of influence on the shortlisting probability."
                    weights={weights.logistic.weights}
                    featureNames={names}
                    type="coefficients"
                    order={sharedOrder}
                  />
                )}
                {weights.gbt && (
                  <ModelCard
                    title="Gradient-Boosted Trees"
                    subtitle="Non-linear model capturing feature interactions: skill × seniority synergy, skill threshold cliff at 0.55, experience-skill substitution, and quadratic constraint gate."
                    weights={weights.gbt.weights}
                    featureNames={names}
                    type="importances"
                    order={sharedOrder}
                  />
                )}
              </div>
            );
          })()
        )}
      </section>
    </div>
  );
}
