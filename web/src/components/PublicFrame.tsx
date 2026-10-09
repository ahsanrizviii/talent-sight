import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import SkyScene from "./SkyScene";

// The frame around the login page: the full scene and the brand.
// The site is for the hiring team only; candidates apply from the blog post.
export default function PublicFrame({ children }: { children: ReactNode }) {
  return (
    <>
      <SkyScene />
      <header className="topbar">
        <nav className="nav" />
        <Link to="/login" className="brand">
          TalentSight
        </Link>
        <div className="topbar-end" />
      </header>
      {children}
    </>
  );
}