// NotFoundPage — catch-all * route.
import React from "react";
import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <div>
      <h1 data-testid="not-found-heading">404 — Page not found</h1>
      <Link to="/" data-testid="not-found-home-link">
        Go home
      </Link>
    </div>
  );
}
