import { Link, NavLink, Outlet } from "react-router-dom";

export default function Layout() {
  return (
    <>
      <header className="topbar">
        <Link to="/" className="brand">TalentSight</Link>
        <nav className="nav">
          <NavLink to="/" end>Home</NavLink>
          <NavLink to="/prototype/video">Video test</NavLink>
        </nav>
      </header>
      <main className="content">
        <Outlet />
      </main>
    </>
  );
}