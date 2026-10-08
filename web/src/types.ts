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