// Mirrors the UI fields of backend/app/contracts.py v1.0.
export type Mode = "recruitment" | "mock";
export interface Evidence {
  source_type: string;
  source_id: string;
  locator: string;
  excerpt: string;
}
export interface Case {
  case_id: string;
  mode: Mode;
  role: string;
  cv_text: string;
  job_description: string;
}
export interface Plan {
  case_id: string;
  plan_version: string;
  questions: {
    question_id: string;
    skill: string;
    question: string;
    evidence: Evidence[];
  }[];
  missing_information: string[];
  warnings: string[];
}
export interface Assessment {
  coverage: number;
  skills: {
    skill: string;
    status: string;
    score: number | null;
    rationale: string;
    evidence: Evidence[];
    needs_verification: boolean;
  }[];
  limitations: string[];
}
export interface Report {
  case_id: string;
  report_version: string;
  mode: Mode;
  summary: string;
  strengths: string[];
  gaps: string[];
  evidence: Evidence[];
  suggested_next_steps: string[];
  learning_resources: { title: string; url: string }[];
  draft_email: string | null;
  approval_status: string;
}
