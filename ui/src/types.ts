export interface ConstraintMatch {
  match_type: string;
  compatible: boolean;
  score: number;
  reason: string;
  flagged: boolean;
}

export interface FeatureVector {
  required_skills_overlap: number;
  preferred_skills_overlap: number;
  industry_preferred_match: number;
  experience_delta: number;
  seniority_match: number;
  career_trajectory_score: number;
  interview_score: number;
  culture_fit_score: number;
  management_match: number;
  soft_constraint_score: number;
}

export interface CandidateRequirement {
  description: string;
  canonical_key: string | null;
  value: string | number | boolean | null;
  operator: string;
  type: "hard" | "soft";
  currency: string | null;
}

export interface RankedCandidate {
  rank: number;
  candidate_id: string;
  name: string;
  score: number;
  explanation: string;
  feature_vector: FeatureVector;
  flagged_for_review: boolean;
  constraint_matches: ConstraintMatch[];
  candidate_requirements?: CandidateRequirement[];
}

export interface EliminatedCandidate {
  candidate_id: string;
  name: string;
  elimination_reason: string;
}

export interface ReviewAlert {
  candidate_id: string;
  candidate_name: string;
  constraint: string;
  reason: string;
  match_type: string;
  score: number;
}

export interface JobConstraint {
  type: "hard" | "soft";
  category: string;
  description: string;
  operator: string;
  canonical_key?: string | null;
  value?: string | number | boolean | null;
  confidence?: number | null;
}

export interface JobDetails {
  company: string;
  seniority: string;
  min_years_experience: number;
  management_required: boolean;
  required_skills: string[];
  preferred_skills: string[];
  industries_preferred: string[];
  constraints: JobConstraint[];
}

export interface RecommendResult {
  job_id: string;
  job_title: string;
  retrieved_candidates: number;
  ranked_candidates: RankedCandidate[];
  eliminated_candidates: EliminatedCandidate[];
  review_alerts: ReviewAlert[];
  weights_used: Record<string, number>;
  profile_used: string;
  job_details?: JobDetails;
}

export interface CandidateRow {
  id: string;
  name: string;
  years_experience: number;
  seniority_level: string;
  skills: string[];
  industries: string[];
  management_experience: boolean;
  career_trajectory: string;
  discipline: string;
}

export interface ProfileInfo {
  weights: Record<string, number>;
  description: string;
}

export type ProfilesResponse = Record<string, ProfileInfo>;

export type PipelineStep =
  | "parsing"
  | "retrieving"
  | "constraints"
  | "scoring"
  | "explaining";

export type StepStatus = "pending" | "active" | "done";

export interface PipelineStepState {
  id: PipelineStep;
  label: string;
  status: StepStatus;
}

// Streaming event types
export interface ShortlistEntry {
  candidate: RankedCandidate;
  note: string;
  removed: boolean;
  manuallyAdded: boolean;
}

export interface HirerCandidate {
  candidate_id: string;
  name: string;
  seniority_level: string;
  skills: string[];
  score: number;
  note: string;
}

export interface ModelStatus {
  trained_at?: string;
  total_records?: number;
  feedback_count: number;
  training_data_count: number;
  models?: {
    logistic?: { auc: number; cv_auc: number };
    gbt?: { auc: number; cv_auc: number };
  };
}

export interface RetrainResult {
  logistic: { auc: number; cv_auc: number };
  gbt: { auc: number; cv_auc: number };
  total_records: number;
  trained_at: string;
}

export interface FeedbackRecord {
  candidate_id: string;
  job_id: string;
  features: number[];
  outcome: 0 | 1;
  source: "recruiter";
}

export type StreamEvent =
  | { type: "step"; step: PipelineStep }
  | {
      type: "meta";
      job_id: string;
      job_title: string;
      job_details: JobDetails;
      ranked_candidates: RankedCandidate[];
      eliminated_candidates: EliminatedCandidate[];
      review_alerts: ReviewAlert[];
      retrieved_candidates: number;
      weights_used: Record<string, number>;
      profile_used: string;
    }
  | { type: "explanation"; rank: number; explanation: string }
  | { type: "done" }
  | { type: "error"; message: string };

// ---------------------------------------------------------------------------
// Live-data PoC (separate pipeline: constraint engine + coarse/fine LLM
// rerank against Mothership's live Supabase data, not synthetic fixtures /
// weighted-linear scoring — see openspec/changes/live-matchmaking-poc)
// ---------------------------------------------------------------------------

export interface LiveJobSummary {
  job_order_id: number;
  job_title: string;
  company_name: string;
  is_open: boolean;
}

export interface LiveFlexibilityNote {
  constraint_description: string;
  flex_judgment: "rigid" | "some_flex" | "likely_flexible";
  reason: string;
}

export interface LiveCoarseBrief {
  summary: string;
  flexibility_notes: LiveFlexibilityNote[];
  requires_uk_based: "yes" | "no" | "unclear";
  offers_visa_sponsorship: "yes" | "no" | "unclear";
}

export type LiveVerdict = "strong_match" | "good_match" | "possible" | "weak_match";

export interface LiveRankedCandidate {
  candidate_id: string;
  name: string;
  verdict: LiveVerdict;
  rationale: string;
  flagged_for_review: boolean;
  matched_skills: string[];
  missing_required_skills: string[];
  years_experience: number;
  seniority_level: string;
  bullhorn_id: string;
  /** "" when BULLHORN_TENANT_URL isn't configured server-side — render the id as plain text, not a link. */
  bullhorn_url: string;
}

export interface LiveEliminatedCandidate {
  candidate_id: string;
  name: string;
  reasons: string[];
}

export interface LiveRecommendResult {
  run_id: string;
  job: { id: string; title: string; company: string };
  coarse_brief: LiveCoarseBrief;
  ranked: LiveRankedCandidate[];
  eliminated: LiveEliminatedCandidate[];
  candidates_considered: number;
  candidates_indexed: number;
  candidates_passed_filter: number;
  candidates_reranked: number;
}

export interface LiveRunSummary {
  run_id: string;
  job_order_id: number;
  completed_at: string;
  title: string;
  company: string;
  candidates_considered: number;
  candidates_passed_filter: number;
  candidates_reranked: number;
}
