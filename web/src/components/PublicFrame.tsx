import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import SkyScene from "./SkyScene";
import ThemeToggle from "./ThemeToggle";

// The frame around the pages anyone can open: the welcome page, logging in and the
// candidate's own interview link. The hiring tool itself has its own frame (Layout).
export default function PublicFrame({ children }: { children: ReactNode }) {
  return (
    <div className="public">
      <SkyScene />
      <header className="topbar">
        <Link to="/welcome" className="brand">
          <span className="brand-mark" aria-hidden="true" />
          TalentSight
        </Link>
        <ThemeToggle />
      </header>
      {children}
    </div>
  );
}
