// The product name and positioning (BID P1.1), kept in one place so every screen says the same thing.

export const NAME = "TalentSight";

export const POSITIONING =
  "TalentSight helps hiring teams find the right candidate faster by screening CVs, capturing interviews and turning both into one evidence-backed assessment.";

export const CATEGORY = "Recruitment Intelligence Platform for Candidate Screening and Interview Assessment";

export const SLOGAN = "Hire on evidence, not instinct";

// The browser tab title of each page, so several open tabs can be told apart.
const TITLES: [RegExp, string][] = [
  [/^\/$/, "Dashboard"],
  [/^\/welcome$/, ""],
  [/^\/login$/, "Log in"],
  [/^\/signup$/, "Sign up"],
  [/^\/join\//, "Your interview"],
  [/^\/jobs$/, "Jobs"],
  [/^\/jobs\/new$/, "New job"],
  [/^\/jobs\/\d+$/, "Edit job"],
  [/^\/jobs\/\d+\/candidates$/, "Job candidates"],
  [/^\/jobs\/\d+\/post$/, "Job post"],
  [/^\/jobs\/\d+\/cvs$/, "CVs received"],
  [/^\/jobs\/\d+\/compare$/, "Compare candidates"],
  [/^\/candidates$/, "Candidates"],
  [/^\/candidates\/\d+$/, "Candidate"],
  [/^\/interviews$/, "Interviews"],
  [/^\/interview\/\d+$/, "Interview room"],
  [/^\/jd-chat/, "Write a job with AI"],
  [/^\/settings$/, "Settings"],
  [/^\/library$/, "Library"],
  [/^\/prototype\/video$/, "Video test"],
];

export function pageTitle(pathname: string): string {
  const found = TITLES.find(([pattern]) => pattern.test(pathname));
  if (!found) return `Page not found – ${NAME}`;
  return found[1] ? `${found[1]} – ${NAME}` : `${NAME} – ${SLOGAN}`;
}