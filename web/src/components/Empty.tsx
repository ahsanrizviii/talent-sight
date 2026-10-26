import type { ReactNode } from "react";

// What a list says when it has nothing in it yet. An empty screen should say what to do next,
// not just that it is empty.
export default function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}
