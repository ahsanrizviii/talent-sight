import { Navigate, Outlet } from "react-router-dom";
import { isLoggedIn } from "../auth";

export default function RequireLogin() {
  return isLoggedIn() ? <Outlet /> : <Navigate to="/login" replace />;
}