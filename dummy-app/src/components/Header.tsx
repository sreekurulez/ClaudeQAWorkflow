// Header — shared component imported by ItemsPage, CartPage, ProfilePage, OrdersPage.
// This is the "high impact" shared component for Catalog 2 (§2.2 point 1):
// changing Header must be traced up to all 4 importing routes.
import React from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

interface HeaderProps {
  title?: string;
}

export function Header({ title = "QA Dummy App" }: HeaderProps) {
  const { auth, logout, isAuthenticated } = useAuth();

  const handleLogout = async () => {
    await fetch("/api/logout", { method: "POST" });
    logout();
  };

  return (
    <header>
      <h1>{title}</h1>
      <nav>
        {isAuthenticated && (
          <>
            <Link to="/items">Items</Link>
            {" | "}
            <Link to="/cart">Cart</Link>
            {" | "}
            <Link to="/orders">Orders</Link>
            {" | "}
            <Link to="/profile">Profile</Link>
            {" | "}
            <span data-testid="current-user-indicator">
              Signed in as {auth.email}
            </span>
            {" | "}
            <button onClick={handleLogout}>Sign out</button>
          </>
        )}
      </nav>
    </header>
  );
}
