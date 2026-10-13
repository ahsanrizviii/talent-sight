import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import SiteFooter from "./SiteFooter";
import SkyScene from "./SkyScene";

// The frame around the pages you can open before logging in: the welcome page, log in and sign up.
// The dusk scene fills the screen behind them, the same scene as behind every working page.
export default function PublicFrame({
  children,
  footer = true,
  full = false,
}: {
  children: ReactNode;
  footer?: boolean;
  full?: boolean; // the scene covers the whole page rather than only the first screen
}) {
  return (
    <div className={full ? "public full" : "public"}>
      <SkyScene />

      <header className="public-bar">
        <nav className="public-links">
          {/* A plain link, not a router Link, so the browser scrolls to the section by itself. */}
          <a href="/welcome#how-it-works">How it works</a>
        </nav>

        <Link to="/welcome" className="brand">
          <span className="brand-mark" aria-hidden="true" />
          TalentSight
        </Link>

        <div className="public-end">
          <Link className="button pill" to="/login">
            Log in
            <span className="arrow-box">
              <svg viewBox="0 0 16 16" aria-hidden="true">
                <path d="M6 3.5 10.5 8 6 12.5" />
              </svg>
            </span>
          </Link>
        </div>
      </header>

      {children}

      {footer && <SiteFooter />}
    </div>
  );
}
