import { Route, Routes } from "react-router-dom";

import Layout from "./components/Layout";
import HomePage from "./pages/HomePage";
import VideoTestPage from "./pages/VideoTestPage";

// Every page of the app and its address.
export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<HomePage />} />
        <Route path="/prototype/video" element={<VideoTestPage />} />
      </Route>
    </Routes>
  );
}