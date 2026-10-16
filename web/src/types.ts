// The shapes of the data the API sends and receives.
// They mirror the Pydantic models in the api folder.

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
  policies?: string[]; // the company policy paragraphs the AI used (RAG)
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

export type CandidateStatus = "uploaded" | "queued" | "screened" | "excluded" | "unreadable" | "failed";

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
  overall: number | null;
  rank: number | null;
};

export type ScoreBreakdown = {
  overall: number;
  dimensions: {
    dimension: string;
    label: string;
    score: number;
    weight: number;
    contribution: number;
    justification: string;
  }[];
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
    languages?: string[];
    projects?: ProfileItem[];
    total_experience_years?: number;
  };
  cv_text: string;
  verdicts: Verdict[];
  score: ScoreBreakdown | null;
};

export type UploadResult = { filename: string; ok: boolean; candidate_id: number | null; error: string };

export type ImportResult = { imported: number; skipped: number; failed: { filename: string; error: string }[] };

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

export type Interview = {
  id: number;
  candidate_id: number;
  candidate_name: string;
  job_title: string;
  scheduled_at: string;
  invite_expires_at: string;
  status: "scheduled" | "live" | "ended";
  started_at: string | null;
  ended_at: string | null;
  invite_url: string;
  email_sent: boolean | null; // null = no e-mail was tried in this answer
  email_error: string;
  calendar_added: boolean | null; // null = Google Calendar is off or was not tried in this answer
  calendar_error: string;
  duration_seconds: number | null; // null until the interview has ended
  duration_minutes: number; // how long it is booked for
  participants: { role: "interviewer" | "candidate"; joined_at: string; left_at: string | null }[];

};

// What the API gives a browser to enter a video room (interviewer and candidate alike).
export type JoinInfo = { livekit_url: string; token: string; room: string; identity: string };


// What the candidate's page may know about their interview (no scores or other candidates).
export type InviteInfo = {
  session_id: number;
  scheduled_at: string;
  opens_at: string;
  status: string;
  candidate_name: string;
  job_title: string;
};


// Live speech to text (Module 8). Times are milliseconds since the interview started (Q&A 31).
export type Speaker = "interviewer" | "candidate";

export type TranscriptSegment = { id: number; speaker: Speaker; text: string; start_ms: number; end_ms: number };

export type Transcript = { session_id: number; status: "scheduled" | "live" | "ended"; segments: TranscriptSegment[] };

// ---------- Looking across every job at once (UI refresh) ----------

// Where a candidate stands in the hiring process, in one word.
export type Stage = "new" | "screened" | "excluded" | "interview" | "interviewed" | "problem";

export type PersonRow = {
  id: number;
  name: string;
  email: string;
  cv_filename: string;
  source: "upload" | "google_form";
  status: CandidateStatus;
  stage: Stage;
  created_at: string;
  job_id: number;
  job_title: string;
  met: number;
  partially_met: number;
  unmet: number;
  overall: number | null;
  rank: number | null;
  interview_id: number | null;
  interview_status: "" | "scheduled" | "live" | "ended";
  interview_at: string | null;
  transcript_lines: number;
};

export type InterviewRow = {
  id: number;
  candidate_id: number;
  candidate_name: string;
  job_id: number;
  job_title: string;
  scheduled_at: string;
  status: "scheduled" | "live" | "ended";
  started_at: string | null;
  ended_at: string | null;
  duration_seconds: number | null;
  transcript_lines: number;
  overall: number | null; // the candidate's score
  duration_minutes: number;
  overdue: boolean;
  forgotten: boolean;
};

export type JobRow = {
  id: number;
  title: string;
  status: "draft" | "published";
  created_at: string;
  blog_url: string | null;
  required_skills: string[];
  candidates: number;
  screened: number;
  waiting: number;
  interviews: number;
  top_score: number | null;
};

export type TodoItem = { text: string; action: string; to: string; tone: "normal" | "warn" };

// One open job on the dashboard: how far its hiring has got, and the next step for it.
export type JobProgress = {
  id: number;
  title: string;
  days_open: number;
  candidates: number;
  waiting: number;
  passed: number;
  invited: number;
  interviewed: number;
  leader_id: number | null;
  leader_name: string;
  leader_score: number | null;
  next_step: string;
  next_link: string;
};

export type Overview = {
  jobs_open: number;
  jobs_total: number;
  candidates_total: number;
  waiting_to_screen: number;
  passed_screening: number;
  ready_total: number;
  interviews_upcoming: number;
  interviews_week: number;
  interviews_done: number;
  funnel: { label: string; value: number }[];
  todo: TodoItem[];
  next_interview: InterviewRow | null;
  upcoming: InterviewRow[];
  jobs: JobProgress[];
  ready_to_invite: PersonRow[];
  recent_interviews: InterviewRow[];
};

// ---------- Accounts ----------

export type Me = { id: number; email: string; name: string; company: string; role: string };

export type SignInOptions = { signup_open: boolean; email_domains: string[]; company_setup_needed: boolean };

// ---------- Kept "Write a job with AI" chats ----------

export type ChatSummary = {
  thread_id: string;
  title: string;
  status: "waiting" | "done" | "failed";
  job_id: number | null;
  created_at: string;
  updated_at: string;
  messages: number;
};

export type ChatMessage = { role: "recruiter" | "assistant"; text: string; at: string };

export type ChatHistory = ChatSummary & { brief: string; lines: ChatMessage[] };

// One line of the setup check: does this part of an interview really work?
export type SetupCheck = {
  key: string;
  label: string;
  ok: boolean;
  detail: string;
  fix: string; // what to change when it does not work; empty when it does
  optional: boolean; // the app works without it, but a company will usually want it
};

// The "new CVs" notice on the job page: CVs that arrived since this person's previous visit.
export type JobVisit = { new_cvs: number; since: string | null };

// The company that uses TalentSight (name and contact in every e-mail), set at the first sign-up.
export type CompanySettings = {
  company_name: string;
  sender_name: string;
  contact_name: string;
  contact_email: string;
  sending_address: string; // the real mailbox (SMTP_USER), set in .env
  from_line: string; // exactly what candidates see in "From"
};

// Inviting the top candidates of a job at once (the pop-up after screening).
export type InviteBatch = {
  id: number;
  created_at: string;
  total: number;
  sent: number;
  failed: number;
  queued: number;
  deliveries: {
    session_id: number;
    candidate_id: number;
    name: string;
    email: string;
    scheduled_at: string;
    duration_minutes: number;
    interview_status: "scheduled" | "live" | "ended";
    status: "queued" | "sent" | "failed";
    error: string;
    calendar_error: string;
  }[];
};

// Shown in the invite pop-up: the holidays the planner skips, or why the holiday calendar was not read.
export type HolidayStatus = { holidays_ahead: number; calendar_problem: string };

export type InviteTopResult = {
  batch: InviteBatch | null; // null when nobody could be invited
  skipped: { candidate_id: number; rank: number; name: string; reason: string }[];
  not_placed: number;
};


// ---------- The answer analysis of an interview (Module 9) ----------

export type QaDimensionKey = "relevance" | "accuracy" | "completeness" | "articulation";

export type QaTurn = { n: number; speaker: Speaker; text: string; start_ms: number; end_ms: number };

export type QaPair = {
  id: number;
  question: string;
  asked: string; // the interviewer's own words
  turns: number[]; // every turn of this exchange, follow-ups included
  answer_turns: number[];
  part: number;
  parts: number; // 2 or more = one part of a multi-part question
  follow_ups: string[];
  start_ms: number;
  kind: "job_related" | "small_talk";
  requirements: number[]; // numbers in the coverage list
  scores: Record<QaDimensionKey, { score: number; justification: string }> | null;
  overall: number | null;
  evidence: { turn: number; start_ms: number; quote: string } | null;
  references: { skill: string; heading: string; url: string }[];
};

export type QaCoverage = {
  number: number;
  requirement: string;
  kind: string;
  mandatory: boolean;
  pairs: number[];
  best_score: number | null;
  status: "explored" | "weak" | "not_explored";
};

export type QaEvaluation = {
  session_id: number;
  status: "running" | "done" | "failed";
  step: string;
  error: string;
  started_at: string;
  finished_at: string | null;
  seconds: number | null;
  turns: QaTurn[];
  pairs: QaPair[];
  coverage: QaCoverage[];
  summary: {
    pairs: number;
    job_related: number;
    small_talk: number;
    scored: number;
    average: number | null;
    not_explored: number;
    weak: number;
  };
};