import { Route, Routes } from "react-router-dom";

import Layout from "./components/Layout";
import RequireLogin from "./components/RequireLogin";
import HomePage from "./pages/HomePage";
import LoginPage from "./pages/LoginPage";
import VideoTestPage from "./pages/VideoTestPage";

export default function App() {
  return (
    <Routes>
      {/* Public */}
      <Route path="/login" element={<LoginPage />} />

      {/* Interviewer only */}
      <Route element={<RequireLogin />}>
        <Route element={<Layout />}>
          <Route path="/" element={<HomePage />} />
          <Route path="/prototype/video" element={<VideoTestPage />} />
        </Route>
      </Route>
    </Routes>
  );
}