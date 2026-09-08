// App.tsx — root router using react-router-dom 6.3.0, JSX <Route> style
// (not createBrowserRouter). This mirrors exactly how finbook's App.tsx declares routes.
//
// Route inventory (Catalog 1 — Route Registry):
//   /                → index route → redirect to /items or /login
//   /login           → LoginPage          (flat route)
//   /items           → ItemsPage          (flat route, landing after login)
//   /items/:id       → ItemDetailPage     (URL parameter)
//   /cart            → CartPage           (layout parent, nested children below)
//   /cart/:itemId    → CartItemPage       (nested, URL parameter)
//   /profile         → ProfilePage        (flat route, not in user-story text → dep-derived)
//   /orders          → OrdersPage         (layout parent, nested children below)
//   /orders/:orderId → OrderDetailPage    (nested, lazy-loaded via React.lazy in OrdersPage)
//   *                → NotFoundPage       (catch-all)
//
// Multi-line JSX attribute style (per finbook formatting — regex-resistant):
//   <Route
//     path="..."
//     element={<Component />}
//   />
import React, { Suspense } from "react";
import {
  BrowserRouter,
  Routes,
  Route,
  Navigate,
} from "react-router-dom";

import { AuthProvider } from "./context/AuthContext";
import { CartProvider } from "./context/CartContext";

import { LoginPage } from "./pages/LoginPage";
import { ItemsPage } from "./pages/ItemsPage";
import { ItemDetailPage } from "./pages/ItemDetailPage";
import { CartPage } from "./pages/CartPage";
import { CartItemPage } from "./pages/CartItemPage";
import { ProfilePage } from "./pages/ProfilePage";
import { OrdersPage } from "./pages/OrdersPage";
import { NotFoundPage } from "./pages/NotFoundPage";

// Second React.lazy dynamic import — Catalog 2 §2.2 point 5 requires 1-2 lazy imports.
// OrderDetailPage is also lazy-loaded inside OrdersPage; this one is at the router level.
const OrderDetailPage = React.lazy(
  () => import("./pages/OrderDetailPage")
);

export default function App() {
  return (
    <AuthProvider>
      <CartProvider>
        <BrowserRouter>
          <Routes>
            {/* Index route — redirects to /items for authenticated users */}
            <Route
              index
              element={<Navigate to="/items" replace />}
            />

            {/* Flat routes */}
            <Route
              path="/login"
              element={<LoginPage />}
            />
            <Route
              path="/items"
              element={<ItemsPage />}
            />
            <Route
              path="/items/:id"
              element={<ItemDetailPage />}
            />
            <Route
              path="/profile"
              element={<ProfilePage />}
            />

            {/* Layout route: /cart wraps /cart/:itemId children */}
            <Route
              path="/cart"
              element={<CartPage />}
            >
              <Route
                path=":itemId"
                element={<CartItemPage />}
              />
            </Route>

            {/* Layout route: /orders wraps /orders/:orderId children */}
            <Route
              path="/orders"
              element={<OrdersPage />}
            >
              <Route
                path=":orderId"
                element={
                  <Suspense fallback={<span>Loading…</span>}>
                    <OrderDetailPage />
                  </Suspense>
                }
              />
            </Route>

            {/* Catch-all */}
            <Route
              path="*"
              element={<NotFoundPage />}
            />
          </Routes>
        </BrowserRouter>
      </CartProvider>
    </AuthProvider>
  );
}
