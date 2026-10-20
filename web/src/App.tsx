import { useEffect } from "react";
import { Route, Routes, useLocation } from "react-router-dom";

import { pageTitle } from "./brand";
import Layout from "./components/Layout";
import RequireLogin from "./components/RequireLogin";
import CandidatePage from "./pages/CandidatePage";
import CandidatesPage from "./pages/CandidatesPage";
import ComparePage from "./pages/ComparePage";
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
import NotFoundPage from "./pages/NotFoundPage";
import PeoplePage from "./pages/PeoplePage";
import VideoTestPage from "./pages/VideoTestPage";

// Names the browser tab after the page, so an interviewer with the room and a profile open can tell them apart.
function PageTitle() {
  const { pathname } = useLocation();
  useEffect(() => {
    document.title = pageTitle(pathname);
  }, [pathname]);
  return null;
}

export default function App() {
  return (
    <>
      <PageTitle />
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
            <Route path="/jobs/:id/compare" element={<ComparePage />} />
            <Route path="/candidates" element={<PeoplePage />} />
            <Route path="/candidates/:id" element={<CandidatePage />} />
            <Route path="/interviews" element={<InterviewsPage />} />
            <Route path="/interview/:id" element={<InterviewRoomPage />} />
            <Route path="/jd-chat" element={<JdChatPage />} />
            <Route path="/jd-chat/:threadId" element={<JdChatPage />} />
            <Route path="/prototype/video" element={<VideoTestPage />} />
            {/* Any other address: a page that says so, instead of a blank screen */}
            <Route path="*" element={<NotFoundPage />} />
          </Route>
        </Route>
      </Routes>
    </>
  );
}