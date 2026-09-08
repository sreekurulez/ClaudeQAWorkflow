// OrdersPage — /orders route.
// Imports Header (shared) and ProductList (which imports CartButton → PriceDisplay).
// So OrdersPage is reached via the transitive chain:
//   PriceDisplay ← CartButton ← ProductList ← OrdersPage
// Also uses React.lazy to load OrderDetailPage — the dynamic import case (§2.2 point 5).
// A static parser will not resolve this; the indexer must report it as unresolved.
import React, { lazy, Suspense, useEffect, useState } from "react";
import { useNavigate, Outlet } from "react-router-dom";
import { Header } from "../components/Header";
import { useAuth } from "../context/AuthContext";

// Dynamic import — Catalog 2 §2.2 point 5: React.lazy must be reported as unresolved
// by a static import parser, not silently dropped.
const OrderDetailPage = lazy(() => import("./OrderDetailPage"));

interface Order {
  id: number;
  itemId: number;
  itemName: string;
  quantity: number;
  status: "pending" | "fulfilled" | "cancelled";
}

export function OrdersPage() {
  const [orders, setOrders] = useState<Order[]>([]);
  const { isAuthenticated } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (!isAuthenticated) navigate("/login");
  }, [isAuthenticated, navigate]);

  useEffect(() => {
    if (isAuthenticated) {
      fetch("/api/orders")
        .then((res) => res.json())
        .then((data) => setOrders(data));
    }
  }, [isAuthenticated]);

  return (
    <section>
      <Header title="Orders" />
      <h2>Your orders</h2>
      <ul data-testid="orders-list">
        {orders.length === 0 && (
          <li data-testid="orders-empty">No orders yet.</li>
        )}
        {orders.map((order) => (
          <li key={order.id} data-testid={`order-row-${order.id}`}>
            <span data-testid={`order-item-name-${order.id}`}>
              {order.itemName}
            </span>
            {" × "}
            <span data-testid={`order-qty-${order.id}`}>{order.quantity}</span>
            {" — "}
            <span data-testid={`order-status-${order.id}`}>{order.status}</span>
            {" "}
            <a
              href={`/orders/${order.id}`}
              data-testid={`order-detail-link-${order.id}`}
            >
              View detail
            </a>
          </li>
        ))}
      </ul>
      {/* Outlet renders nested /orders/:orderId route */}
      <Suspense fallback={<span>Loading order detail…</span>}>
        <Outlet />
      </Suspense>
    </section>
  );
}

// Re-export the lazy component so it can be used by App.tsx in the nested route
export { OrderDetailPage };
