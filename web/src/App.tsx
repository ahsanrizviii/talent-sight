import { Route, Routes } from "react-router-dom";

import Layout from "./components/Layout";
import RequireLogin from "./components/RequireLogin";
import CandidatePage from "./pages/CandidatePage";
import CandidatesPage from "./pages/CandidatesPage";
import HomePage from "./pages/HomePage";
import JdChatPage from "./pages/JdChatPage";
import JobFormPage from "./pages/JobFormPage";
import JobsPage from "./pages/JobsPage";
import LoginPage from "./pages/LoginPage";
import VideoTestPage from "./pages/VideoTestPage";
import InterviewRoomPage from "./pages/InterviewRoomPage";



export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />

      {/* Interviewer only */}
      <Route element={<RequireLogin />}>
        <Route element={<Layout />}>
          <Route path="/" element={<HomePage />} />
          <Route path="/jobs" element={<JobsPage />} />
          <Route path="/jobs/new" element={<JobFormPage />} />
          <Route path="/jobs/:id" element={<JobFormPage />} />
          <Route path="/jobs/:id/candidates" element={<CandidatesPage />} />
          <Route path="/candidates/:id" element={<CandidatePage />} />
          <Route path="/interview/:id" element={<InterviewRoomPage />} />
          <Route path="/jd-chat" element={<JdChatPage />} />
          <Route path="/prototype/video" element={<VideoTestPage />} />
        </Route>
      </Route>
    </Routes>
  );
}