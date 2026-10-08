export type Weights = {
  technical_skills: number;
  experience: number;
  qualifications: number;
  jd_match: number;
};

export type JobInput = {
  title: string;
  description: string;
  required_skills: string[];
  preferred_skills: string[];
  qualifications: string[];
  min_experience_years: number;
  selection_criteria: string;
  weights: Weights;
};

export type Job = JobInput & {
  id: number;
  status: "draft" | "published";
  slug: string | null;
  blog_url: string | null;
  created_at: string;
};

export type ChatState = {
  thread_id: string;
  status: "waiting" | "done" | "failed";
  kind: "questions" | "draft" | null;
  questions: string[];
  draft: JobInput | null;
  job_id: number | null;
  slug: string | null;
  blog_url: string | null;
  message: string;
};

export type PublicJobSummary = {
  slug: string;
  title: string;
  min_experience_years: number;
};

export type PublicJob = {
  title: string;
  description: string;
  required_skills: string[];
  preferred_skills: string[];
  qualifications: string[];
  min_experience_years: number;
  apply_email: string;
  apply_url: string | null;
};

export type Verdict = {
  requirement: string;
  kind: "skill" | "qualification" | "experience" | "preferred";
  mandatory: boolean;
  verdict: "met" | "partially_met" | "unmet";
  explanation: string;
};

export type CandidateStatus =
  | "uploaded"
  | "queued"
  | "screened"
  | "excluded"
  | "unreadable"
  | "failed";

export type CandidateRow = {
  id: number;
  name: string;
  email: string;
  cv_filename: string;
  source: "upload" | "google_form";
  status: CandidateStatus;
  text_method: string;
  exclusion_reason: string;
  error: string;
  created_at: string;
  met: number;
  partially_met: number;
  unmet: number;
};

type ProfileItem = Record<string, string>;

export type CandidateDetail = CandidateRow & {
  job_profile_id: number;
  phone: string;
  profile: {
    education?: ProfileItem[];
    work_history?: ProfileItem[];
    skills?: string[];
    certifications?: string[];
    projects?: ProfileItem[];
    total_experience_years?: number;
  };
  verdicts: Verdict[];
};

export type UploadResult = {
  filename: string;
  ok: boolean;
  candidate_id: number | null;
  error: string;
};

export type ImportResult = {
  imported: number;
  skipped: number;
  failed: { filename: string; error: string }[];
};

export type ScreeningRun = {
  id: number;
  status: "running" | "done" | "interrupted";
  total: number;
  done: number;
  failed: number;
  started_at: string;
  finished_at: string | null;
  seconds: number | null;
};