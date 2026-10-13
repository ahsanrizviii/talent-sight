import { useEffect, useState, type FormEvent } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { api } from "../api";
import { clearToken } from "../auth";
import Icon, { type IconName } from "./Icon";
import ThemeToggle from "./ThemeToggle";

type Me = { email: string; name: string; company: string };
type Counts = { candidates_total: number; interviews_upcoming: number; jobs_open: number };

const SECTIONS: { to: string; label: string; icon: IconName; end?: boolean }[] = [
  { to: "/", label: "Dashboard", icon: "dashboard", end: true },
  { to: "/jobs", label: "Jobs", icon: "jobs" },
  { to: "/candidates", label: "Candidates", icon: "people" },
  { to: "/interviews", label: "Interviews", icon: "interviews" },
  { to: "/jd-chat", label: "Write a job with AI", icon: "sparkle" },
];

// The frame around every page of the hiring tool: the sections on the left, search and
// account on top. The sidebar never moves, so the place you are in is always visible.
export default function Layout() {
  const navigate = useNavigate();
  const location = useLocation();
  const [me, setMe] = useState<Me | null>(null);
  const [counts, setCounts] = useState<Counts | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    api<Me>("/auth/me").then(setMe).catch(() => undefined);
  }, []);

  // The numbers beside the sections are reloaded on every page change, so they stay honest.
  useEffect(() => {
    api<Counts>("/workspace/overview").then(setCounts).catch(() => undefined);
  }, [location.pathname]);

  function search(event: FormEvent) {
    event.preventDefault();
    navigate(`/candidates?q=${encodeURIComponent(query.trim())}`);
  }

  function logOut() {
    clearToken();
    navigate("/login");
  }

  const badges: Record<string, number | undefined> = {
    "/jobs": counts?.jobs_open,
    "/candidates": counts?.candidates_total,
    "/interviews": counts?.interviews_upcoming,
  };

  return (
    <div className="shell">
      <nav className="side" aria-label="Sections">
        <Link to="/" className="brand">
          <span className="brand-mark" aria-hidden="true" />
          TalentSight
        </Link>

        {SECTIONS.map((section) => (
          <NavLink key={section.to} to={section.to} end={section.end}>
            <Icon name={section.icon} />
            {section.label}
            {badges[section.to] !== undefined && <span className="side-count">{badges[section.to]}</span>}
          </NavLink>
        ))}

        <div className="side-foot">
          <div className="side-user">
            <strong>{me?.name || "Signed in"}</strong>
            <span>{me?.email}</span>
          </div>
          <button className="button quiet" type="button" onClick={logOut}>
            <Icon name="logout" />
            Log out
          </button>
        </div>
      </nav>

      <div>
        <header className="topbar">
          <form className="search" onSubmit={search} role="search">
            <Icon name="search" />
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search candidates by name, e-mail or job"
              aria-label="Search candidates"
            />
          </form>
          <div className="row" style={{ marginLeft: "auto", gap: 8 }}>
            <ThemeToggle />
          </div>
        </header>

        {/* The key makes React draw a new page, so the arrival animation runs on every move. */}
        <main className="content page" key={location.pathname}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
