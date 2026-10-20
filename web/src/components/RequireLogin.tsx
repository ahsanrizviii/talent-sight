import { Navigate, Outlet, useLocation } from "react-router-dom";
import { isLoggedIn } from "../auth";

// Someone who is not logged in and opens the app lands on the welcome page. Someone who opened a
// particular page (a candidate link from a colleague, say) goes straight to log in, and comes back
// to that page afterwards.
export default function RequireLogin() {
  const location = useLocation();
  if (isLoggedIn()) return <Outlet />;
  if (location.pathname === "/") return <Navigate to="/welcome" replace />;
  const next = location.pathname + location.search;
  return <Navigate to={`/login?next=${encodeURIComponent(next)}`} replace />;
}