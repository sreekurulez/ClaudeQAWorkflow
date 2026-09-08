// LoginPage — preserves all golden-suite testids exactly:
//   login-email, login-password, login-submit, login-error
// After successful login, redirects to /items.
import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export function LoginPage() {
  const [error, setError] = useState("");
  const { login } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget;
    const email = (form.elements.namedItem("email") as HTMLInputElement).value;
    const password = (form.elements.namedItem("password") as HTMLInputElement)
      .value;

    const res = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });

    if (!res.ok) {
      setError("Invalid credentials");
      return;
    }

    const { token } = await res.json();
    login(email, token);
    navigate("/items");
  };

  return (
    <section id="login-section">
      <h1>Sign in</h1>
      <form id="login-form" onSubmit={handleSubmit}>
        <label htmlFor="email">Email</label>
        <input
          id="email"
          name="email"
          type="email"
          data-testid="login-email"
        />
        <label htmlFor="password">Password</label>
        <input
          id="password"
          name="password"
          type="password"
          data-testid="login-password"
        />
        <button type="submit" data-testid="login-submit">
          Sign in
        </button>
      </form>
      {error && (
        <p id="login-error" data-testid="login-error">
          {error}
        </p>
      )}
    </section>
  );
}
