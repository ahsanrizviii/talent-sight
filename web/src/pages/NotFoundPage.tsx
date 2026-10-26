import { Link } from "react-router-dom";

import Empty from "../components/Empty";

// A wrong or old link inside the app: say so, and offer the two places people usually want.
export default function NotFoundPage() {
  return (
    <div className="card glass">
      <Empty
        title="This page does not exist"
        action={
          <div className="row">
            <Link className="button" to="/">
              Go to the dashboard
            </Link>
            <Link className="button secondary" to="/candidates">
              Find a candidate
            </Link>
          </div>
        }
      >
        The link may be old, or the job or candidate may have been deleted. Use the menu above to find what you need.
      </Empty>
    </div>
  );
}