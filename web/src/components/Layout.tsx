import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { clearToken } from "../auth";
import Arrow from "./Arrow";
import SkyScene from "./SkyScene";

export default function Layout() {
  const navigate = useNavigate();

  function logout() {
    clearToken();
    navigate("/login");
  }

  return (
    <>
      <SkyScene variant="calm" />
      <header className="topbar">
        <nav className="nav">
          <NavLink to="/" end>
            Home
          </NavLink>
          <NavLink to="/jobs">Jobs</NavLink>
          <NavLink to="/jd-chat">Write a job with AI</NavLink>
        </nav>

        <Link to="/" className="brand">
          TalentSight
        </Link>

        <div className="topbar-end">
          <button className="button arrow" onClick={logout}>
            Log out <Arrow />
          </button>
        </div>
      </header>

      <main className="content">
        <Outlet />
      </main>
    </>
  );
}