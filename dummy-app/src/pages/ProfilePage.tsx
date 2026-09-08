// ProfilePage — /profile route.
// Shares the Header component (one of 4 routes that does).
// Deliberate scope resolution trap: the user story (US-001) talks about "items" and
// "cart" but does NOT mention "profile". ProfilePage is still affected if Header
// changes — so the dependency-derived route inclusion test kicks in here (§2.6).
import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Header } from "../components/Header";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../components/Toast";
import { useEffect } from "react";

export function ProfilePage() {
  const { auth, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState(auth.email || "");
  const { showToast, ToastComponent } = useToast();

  useEffect(() => {
    if (!isAuthenticated) navigate("/login");
  }, [isAuthenticated, navigate]);

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    // Stub — in-memory only, no real persistence
    showToast("Profile saved");
  };

  return (
    <section>
      <Header title="Profile" />
      <h2>Your profile</h2>
      <form onSubmit={handleSave}>
        <label htmlFor="profile-username">Email / username</label>
        <input
          id="profile-username"
          data-testid="profile-username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
        />
        <button type="submit" data-testid="profile-save-button">
          Save profile
        </button>
      </form>
      {ToastComponent}
    </section>
  );
}
