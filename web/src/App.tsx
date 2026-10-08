import { Route, Routes } from "react-router-dom";

import Layout from "./components/Layout";
import RequireLogin from "./components/RequireLogin";
import CandidatePage from "./pages/CandidatePage";
import CandidatesPage from "./pages/CandidatesPage";
import CareersPage from "./pages/CareersPage";
import HomePage from "./pages/HomePage";
import JdChatPage from "./pages/JdChatPage";
import JobFormPage from "./pages/JobFormPage";
import JobPostPage from "./pages/JobPostPage";
import JobsPage from "./pages/JobsPage";
import LoginPage from "./pages/LoginPage";
import VideoTestPage from "./pages/VideoTestPage";

// Every page of the app and its address.
export default function App() {
  return (
    <Routes>
      {/* Public */}
      <Route path="/login" element={<LoginPage />} />
      <Route path="/careers" element={<CareersPage />} />
      <Route path="/careers/:slug" element={<JobPostPage />} />

      {/* Interviewer only */}
      <Route element={<RequireLogin />}>
        <Route element={<Layout />}>
          <Route path="/" element={<HomePage />} />
          <Route path="/jobs" element={<JobsPage />} />
          <Route path="/jobs/new" element={<JobFormPage />} />
          <Route path="/jobs/:id" element={<JobFormPage />} />
          <Route path="/jobs/:id/candidates" element={<CandidatesPage />} />
          <Route path="/candidates/:id" element={<CandidatePage />} />
          <Route path="/jd-chat" element={<JdChatPage />} />
          <Route path="/prototype/video" element={<VideoTestPage />} />
        </Route>
      </Route>
    </Routes>
  );
}