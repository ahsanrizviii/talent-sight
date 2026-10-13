import { Navigate, Outlet } from "react-router-dom";
import { isLoggedIn } from "../auth";

// Someone who is not logged in lands on the welcome page, where they can log in or
// open an account, rather than on a bare login form.
export default function RequireLogin() {
  return isLoggedIn() ? <Outlet /> : <Navigate to="/welcome" replace />;
}
