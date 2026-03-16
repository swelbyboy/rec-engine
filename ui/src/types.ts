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
export type StreamEvent =
  | { type: "step"; step: PipelineStep }
  | {
      type: "meta";
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
