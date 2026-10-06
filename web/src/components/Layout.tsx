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
        <Link to="/" className="brand">TalentSight</Link>
        <nav className="nav">
          <NavLink to="/" end>Home</NavLink>
          <NavLink to="/prototype/video">Video test</NavLink>
        </nav>
        <button className="button secondary" onClick={logout}>Log out</button>
      </header>
      <main className="content">
        <Outlet />
      </main>
    </>
  );
}