import { Outlet, useLocation } from "react-router-dom";

import SiteFooter from "./SiteFooter";
import SkyScene from "./SkyScene";
import TopNav from "./TopNav";

// The frame around every working page. The morning scene stays fixed behind everything and
// never reloads, so moving between sections changes the content and nothing else. The content
// floats above it on frosted glass: the scene shows in the gaps and through the edges, while
// the text sits on a surface solid enough to read a table on.
export default function Layout() {
  const location = useLocation();

  return (
    <div className="app">
      <SkyScene />
      <TopNav />

      {/* The key makes React draw a new page, so the arrival animation runs on every move. */}
      <main className="content page" key={location.pathname}>
        <Outlet />
      </main>

      <SiteFooter />
    </div>
  );
}
