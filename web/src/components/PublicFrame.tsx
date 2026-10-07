import type { ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import Arrow from "./Arrow";
import SkyScene from "./SkyScene";

// The frame around the public pages (login, careers): the full scene and a simple header.
export default function PublicFrame({ children }: { children: ReactNode }) {
  const onLoginPage = useLocation().pathname.startsWith("/login");

  return (
    <>
      <SkyScene />
      <header className="topbar">
        <nav className="nav">
          <NavLink to="/careers">Open positions</NavLink>
          <NavLink to="/login">Interviewer login</NavLink>
        </nav>

        <Link to="/careers" className="brand">
          TalentSight
        </Link>

        <div className="topbar-end">
          {onLoginPage ? (
            <Link className="button arrow" to="/careers">
              View open positions <Arrow />
            </Link>
          ) : (
            <Link className="button arrow" to="/login">
              Interviewer login <Arrow />
            </Link>
          )}
        </div>
      </header>
      {children}
    </>
  );
}
