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

export interface RankedCandidate {
  rank: number;
  candidate_id: string;
  name: string;
  score: number;
  explanation: string;
  feature_vector: FeatureVector;
  flagged_for_review: boolean;
  constraint_matches: ConstraintMatch[];
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

export interface RecommendResult {
  job_id: string;
  job_title: string;
  retrieved_candidates: number;
  ranked_candidates: RankedCandidate[];
  eliminated_candidates: EliminatedCandidate[];
  review_alerts: ReviewAlert[];
  weights_used: Record<string, number>;
  profile_used: string;
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
