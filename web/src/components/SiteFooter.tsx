import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api";
import type { SignInOptions } from "../types";

// The foot of every page. Only the company's hiring team uses this site (candidates only ever see
// their own interview link), so the foot is one slim band: the name on the left, the workspace
// links in a single line on the right, and the copyright under them.
const LINKS = [
  { label: "Dashboard", to: "/" },
  { label: "Jobs", to: "/jobs" },
  { label: "Candidates", to: "/candidates" },
  { label: "Interviews", to: "/interviews" },
  { label: "Write a job with AI", to: "/jd-chat" },
];

export default function SiteFooter() {
  const [company, setCompany] = useState("");

  useEffect(() => {
    api<SignInOptions>("/auth/options")
      .then((body) => setCompany(body.company))
      .catch(() => undefined);
  }, []);

  return (
    <footer className="foot">
      <div className="foot-inner">
        <div className="foot-brand">
          <Link to="/" className="brand">
            <span className="brand-mark" aria-hidden="true" />
            TalentSight
          </Link>
          <p>Hire on evidence, not instinct.</p>
        </div>

        <nav className="foot-links" aria-label="Workspace">
          {LINKS.map((link) => (
            <Link key={link.to} to={link.to}>
              {link.label}
            </Link>
          ))}
        </nav>
      </div>

      <div className="foot-bottom">
        <span>© {new Date().getFullYear()} TalentSight</span>
        {company && <span>For the hiring team at {company}</span>}
      </div>
    </footer>
  );
}
