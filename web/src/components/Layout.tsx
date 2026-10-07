import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { clearToken } from "../auth";

export default function Layout() {
  const navigate = useNavigate();

  function logout() {
    clearToken();
    navigate("/login");
  }

  return (
    <>
      <header className="topbar">
        <Link to="/" className="brand">
          TalentSight
        </Link>

        <nav className="nav">
          <NavLink to="/" end>
            Home
          </NavLink>
          <NavLink to="/jobs">Jobs</NavLink>
          <NavLink to="/jd-chat">Write a job with AI</NavLink>
          <NavLink to="/prototype/video">Video test</NavLink>
          <a href="/careers" target="_blank" rel="noreferrer">
            Careers page
          </a>
        </nav>

        <button className="button secondary" onClick={logout}>
          Log out
        </button>
      </header>

      <main className="content">
        <Outlet />
      </main>
    </>
  );
}