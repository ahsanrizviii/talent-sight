import { Fragment } from "react";
import { Link } from "react-router-dom";

// Where this page sits, as a trail of links: Jobs › Junior AI Engineer › Rizvi Kabir.
// The last item is the page itself, so it is plain text. Replaces the single "back" links.
export type Crumb = { label: string; to?: string };

export default function Breadcrumbs({ items }: { items: Crumb[] }) {
  return (
    <nav className="crumbs" aria-label="You are here">
      {items.map((item, index) => (
        <Fragment key={`${item.label}-${index}`}>
          {index > 0 && (
            <span className="crumb-sep" aria-hidden="true">
              ›
            </span>
          )}
          {item.to && index < items.length - 1 ? (
            <Link to={item.to}>{item.label}</Link>
          ) : (
            <span aria-current={index === items.length - 1 ? "page" : undefined}>{item.label}</span>
          )}
        </Fragment>
      ))}
    </nav>
  );
}
