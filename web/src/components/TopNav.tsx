import { useEffect, useLayoutEffect, useRef, useState, type FormEvent } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";

import { api } from "../api";
import { clearToken } from "../auth";
import Icon from "./Icon";

type Me = { email: string; name: string; company: string };

const SECTIONS = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/jobs", label: "Jobs" },
  { to: "/candidates", label: "Candidates" },
  { to: "/interviews", label: "Interviews" },
  { to: "/jd-chat", label: "Write with AI" },
];

// The floating bar at the top of every working page: one glass capsule holding the brand,
// the sections, search and the account. The dark marker behind the section you are on is a
// single element that slides, so moving between sections reads as one movement.
export default function TopNav() {
  const navigate = useNavigate();
  const location = useLocation();
  const [me, setMe] = useState<Me | null>(null);
  const [query, setQuery] = useState("");
  const [openMenu, setOpenMenu] = useState(false);
  const [marker, setMarker] = useState({ left: 0, width: 0, ready: false });
  const bar = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api<Me>("/auth/me").then(setMe).catch(() => undefined);
  }, []);

  // Measure the selected link and move the marker onto it. useLayoutEffect, so the marker is
  // in place before the browser paints and never flashes in the wrong spot.
  //
  // It is measured again when the web font finishes loading and whenever the window is resized,
  // because both change how wide the words are and the marker is positioned in pixels.
  useLayoutEffect(() => {
    function measure() {
      const selected = bar.current?.querySelector<HTMLElement>("a.active");
      if (!selected) return;
      setMarker({ left: selected.offsetLeft, width: selected.offsetWidth, ready: true });
    }

    measure();
    document.fonts?.ready.then(measure).catch(() => undefined);
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [location.pathname]);

  useEffect(() => {
    if (!openMenu) return;
    const close = () => setOpenMenu(false);
    window.addEventListener("click", close);
    return () => window.removeEventListener("click", close);
  }, [openMenu]);

  function search(event: FormEvent) {
    event.preventDefault();
    navigate(`/candidates?q=${encodeURIComponent(query.trim())}`);
  }

  function logOut() {
    clearToken();
    navigate("/welcome");
  }

  return (
    <header className="topnav">
      <div className="navbar glass">
        <Link to="/" className="brand">
          <span className="brand-mark" aria-hidden="true" />
          TalentSight
        </Link>

        <nav className="navbar-links" ref={bar} aria-label="Sections">
          <span
            className="navbar-marker"
            style={{ left: marker.left, width: marker.width, opacity: marker.ready ? 1 : 0 }}
            aria-hidden="true"
          />
          {SECTIONS.map((section) => (
            <NavLink key={section.to} to={section.to} end={section.end}>
              {section.label}
            </NavLink>
          ))}
        </nav>

        <form className="search" onSubmit={search} role="search">
          <Icon name="search" />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search candidates"
            aria-label="Search candidates"
          />
        </form>

        <div className="account">
          <button
            className="account-button"
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              setOpenMenu(!openMenu);
            }}
            aria-expanded={openMenu}
            aria-label="Your account"
          >
            {(me?.name || "?").trim().charAt(0).toUpperCase()}
          </button>
          {openMenu && (
            <div className="menu glass" onClick={(event) => event.stopPropagation()}>
              <div className="menu-who">
                <strong>{me?.name}</strong>
                <span>{me?.email}</span>
              </div>
              <Link className="menu-item" to="/settings" onClick={() => setOpenMenu(false)}>
                <Icon name="settings" />
                Settings
              </Link>
              <button className="menu-item" type="button" onClick={logOut}>
                <Icon name="logout" />
                Log out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
