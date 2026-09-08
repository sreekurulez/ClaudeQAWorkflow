// ItemsPage — main item management page.
// Preserved golden-suite elements:
//   - data-testid="item-list"  (via ProductList component)
//   - data-testid="current-user-indicator"  (via Header component)
//   - Delete button: NO data-testid — stays role-fallback (scenario 5)
//   - confirm-delete-button / cancel-delete-button (via ConfirmDialog)
// New testability gap:
//   - Sort toggle button: NO data-testid — second role-fallback element (§2.3)
import React, { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Header } from "../components/Header";
import { ProductList, Item } from "../components/ProductList";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { useToast } from "../components/Toast";
import { useAuth } from "../context/AuthContext";

export function ItemsPage() {
  const [items, setItems] = useState<Item[]>([]);
  const [search, setSearch] = useState("");
  const [sorted, setSorted] = useState(false);
  const [itemToDelete, setItemToDelete] = useState<number | null>(null);
  const [newItemName, setNewItemName] = useState("");
  const { isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const { showToast, ToastComponent } = useToast();

  useEffect(() => {
    if (!isAuthenticated) navigate("/login");
  }, [isAuthenticated, navigate]);

  const loadItems = useCallback(async () => {
    const q = search ? `?q=${encodeURIComponent(search)}` : "";
    const res = await fetch(`/api/items${q}`);
    let data: Item[] = await res.json();
    if (sorted) {
      data = [...data].sort((a, b) => a.name.localeCompare(b.name));
    }
    setItems(data);
  }, [search, sorted]);

  useEffect(() => {
    if (isAuthenticated) loadItems();
  }, [isAuthenticated, loadItems]);

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newItemName.trim()) return;
    await fetch("/api/items", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newItemName.trim() }),
    });
    setNewItemName("");
    showToast("Item added");
    loadItems();
  };

  const handleEdit = async (id: number, newName: string) => {
    await fetch(`/api/items/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newName }),
    });
    showToast("Item updated");
    loadItems();
  };

  const requestDelete = (id: number) => setItemToDelete(id);

  const confirmDelete = async () => {
    if (itemToDelete === null) return;
    const res = await fetch(`/api/items/${itemToDelete}`, { method: "DELETE" });
    if (res.status === 403) {
      const body = await res.json();
      showToast(body.error || "Cannot delete");
    } else {
      showToast("Item deleted");
    }
    setItemToDelete(null);
    loadItems();
  };

  return (
    <section id="items-section">
      <Header title="Items" />

      <form onSubmit={handleAdd}>
        <label htmlFor="item-name">New item</label>
        <input
          id="item-name"
          data-testid="item-name-input"
          value={newItemName}
          onChange={(e) => setNewItemName(e.target.value)}
        />
        <button type="submit" data-testid="add-item-submit">
          Add item
        </button>
      </form>

      <div style={{ marginTop: 10, marginBottom: 10 }}>
        <label htmlFor="search-input">Search:</label>
        <input
          id="search-input"
          data-testid="search-input"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {/* NO data-testid — second role-fallback element for §2.3 */}
        <button onClick={() => setSorted((s) => !s)}>
          {sorted ? "Unsort" : "Sort A–Z"}
        </button>
      </div>

      <ProductList
        items={items}
        onEdit={handleEdit}
        onDelete={requestDelete}
      />

      <ConfirmDialog
        isOpen={itemToDelete !== null}
        message="Are you sure you want to delete this item?"
        onConfirm={confirmDelete}
        onCancel={() => setItemToDelete(null)}
      />

      {ToastComponent}
    </section>
  );
}
