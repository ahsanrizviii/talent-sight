import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import Arrow from "./Arrow";
import SiteFooter from "./SiteFooter";
import SkyScene from "./SkyScene";

// The frame around the pages you can open before logging in: the welcome page, log in and sign up.
// The mountain scene fills the screen behind them, the same scene as behind every working page.
// The bar has three parts: a link on the left, the name in the middle, log in on the right.
export default function PublicFrame({
  children,
  footer = true,
  full = false,
  loginButton = true,
}: {
  children: ReactNode;
  footer?: boolean;
  full?: boolean; // the scene covers the whole page rather than only the first screen
  loginButton?: boolean; // the welcome page has its own Log in button, so it turns this one off
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

        {/* The empty div stays when the button is hidden, so the name remains centred. */}
        <div className="public-end">
          {loginButton && (
            <Link className="button pill" to="/login">
              Log in
              <Arrow />
            </Link>
          )}
        </div>
      </header>

      {children}

      {footer && <SiteFooter />}
    </div>
  );
}
