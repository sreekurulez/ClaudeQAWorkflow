// ItemDetailPage — /items/:id route (URL parameter case for Catalog 1).
import React, { useEffect, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { Header } from "../components/Header";
import { useToast } from "../components/Toast";
import { useAuth } from "../context/AuthContext";

interface Item {
  id: number;
  name: string;
  price?: number;
}

export function ItemDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [item, setItem] = useState<Item | null>(null);
  const [editName, setEditName] = useState("");
  const [editing, setEditing] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const { isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const { showToast, ToastComponent } = useToast();

  useEffect(() => {
    if (!isAuthenticated) navigate("/login");
  }, [isAuthenticated, navigate]);

  useEffect(() => {
    if (!id) return;
    fetch(`/api/items/${id}`)
      .then((res) => {
        if (res.status === 404) {
          setNotFound(true);
          return null;
        }
        return res.json();
      })
      .then((data) => {
        if (data) {
          setItem(data);
          setEditName(data.name);
        }
      });
  }, [id]);

  const handleSave = async () => {
    if (!item || !editName.trim()) return;
    await fetch(`/api/items/${item.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: editName.trim() }),
    });
    setItem({ ...item, name: editName.trim() });
    setEditing(false);
    showToast("Item saved");
  };

  if (notFound) return <p data-testid="item-detail-not-found">Item not found.</p>;
  if (!item) return <p>Loading…</p>;

  return (
    <section>
      <Header title="Item Detail" />
      <Link to="/items" data-testid="item-detail-back">
        ← Back to items
      </Link>
      <h2>
        {editing ? (
          <input
            data-testid="item-detail-name-input"
            value={editName}
            onChange={(e) => setEditName(e.target.value)}
          />
        ) : (
          <span data-testid="item-detail-name">{item.name}</span>
        )}
      </h2>
      {editing ? (
        <>
          <button data-testid="item-detail-save-button" onClick={handleSave}>
            Save
          </button>
          <button
            data-testid="item-detail-cancel-button"
            onClick={() => setEditing(false)}
          >
            Cancel
          </button>
        </>
      ) : (
        <button
          data-testid="item-detail-edit-button"
          onClick={() => setEditing(true)}
        >
          Edit
        </button>
      )}
      {ToastComponent}
    </section>
  );
}
