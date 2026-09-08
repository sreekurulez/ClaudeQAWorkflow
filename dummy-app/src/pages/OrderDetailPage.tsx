// OrderDetailPage — /orders/:orderId route.
// Loaded via React.lazy in OrdersPage — this is the dynamic import the static parser
// cannot resolve (Catalog 2 §2.2 point 5).
import React, { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useToast } from "../components/Toast";

interface Order {
  id: number;
  itemId: number;
  itemName: string;
  quantity: number;
  status: "pending" | "fulfilled" | "cancelled";
}

export default function OrderDetailPage() {
  const { orderId } = useParams<{ orderId: string }>();
  const [order, setOrder] = useState<Order | null>(null);
  const [notFound, setNotFound] = useState(false);
  const navigate = useNavigate();
  const { showToast, ToastComponent } = useToast();

  useEffect(() => {
    if (!orderId) return;
    fetch(`/api/orders/${orderId}`)
      .then((res) => {
        if (res.status === 404) {
          setNotFound(true);
          return null;
        }
        return res.json();
      })
      .then((data) => {
        if (data) setOrder(data);
      });
  }, [orderId]);

  const handleCancel = async () => {
    if (!order) return;
    const res = await fetch(`/api/orders/${order.id}/cancel`, {
      method: "PUT",
    });
    if (res.ok) {
      setOrder({ ...order, status: "cancelled" });
      showToast("Order cancelled");
    }
  };

  if (notFound)
    return <p data-testid="order-detail-not-found">Order not found.</p>;
  if (!order) return <p>Loading…</p>;

  return (
    <div>
      <h3 data-testid="order-detail-heading">Order #{order.id}</h3>
      <p>
        Item:{" "}
        <span data-testid="order-detail-item-name">{order.itemName}</span>
      </p>
      <p>
        Quantity:{" "}
        <span data-testid="order-detail-quantity">{order.quantity}</span>
      </p>
      <p>
        Status:{" "}
        <span data-testid="order-status">{order.status}</span>
      </p>
      {order.status === "pending" && (
        <button data-testid="order-cancel-button" onClick={handleCancel}>
          Cancel order
        </button>
      )}
      <button
        data-testid="order-detail-back"
        onClick={() => navigate("/orders")}
      >
        ← Back to orders
      </button>
      {ToastComponent}
    </div>
  );
}
