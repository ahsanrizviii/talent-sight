import { Route, Routes } from "react-router-dom";

import Layout from "./components/Layout";
import RequireLogin from "./components/RequireLogin";
import CandidatePage from "./pages/CandidatePage";
import CandidatesPage from "./pages/CandidatesPage";
import DashboardPage from "./pages/DashboardPage";
import InterviewRoomPage from "./pages/InterviewRoomPage";
import InterviewsPage from "./pages/InterviewsPage";
import JdChatPage from "./pages/JdChatPage";
import JobCvsPage from "./pages/JobCvsPage";
import JobFormPage from "./pages/JobFormPage";
import JobPostPage from "./pages/JobPostPage";
import JobsPage from "./pages/JobsPage";
import JoinPage from "./pages/JoinPage";
import LandingPage from "./pages/LandingPage";
import LoginPage from "./pages/LoginPage";
import PeoplePage from "./pages/PeoplePage";
import VideoTestPage from "./pages/VideoTestPage";

export default function App() {
  return (
    <Routes>
      {/* Public: anyone can open these without an account */}
      <Route path="/welcome" element={<LandingPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<LoginPage startOn="signup" />} />

      {/* Public: the candidate opens this from the e-mail, no login */}
      <Route path="/join/:token" element={<JoinPage />} />

      {/* The hiring team */}
      <Route element={<RequireLogin />}>
        <Route element={<Layout />}>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/jobs" element={<JobsPage />} />
          <Route path="/jobs/new" element={<JobFormPage />} />
          <Route path="/jobs/:id" element={<JobFormPage />} />
          <Route path="/jobs/:id/candidates" element={<CandidatesPage />} />
          <Route path="/jobs/:id/post" element={<JobPostPage />} />
          <Route path="/jobs/:id/cvs" element={<JobCvsPage />} />
          <Route path="/candidates" element={<PeoplePage />} />
          <Route path="/candidates/:id" element={<CandidatePage />} />
          <Route path="/interviews" element={<InterviewsPage />} />
          <Route path="/interview/:id" element={<InterviewRoomPage />} />
          <Route path="/jd-chat" element={<JdChatPage />} />
          <Route path="/jd-chat/:threadId" element={<JdChatPage />} />
          <Route path="/prototype/video" element={<VideoTestPage />} />
        </Route>
      </Route>
    </Routes>
  );
}
