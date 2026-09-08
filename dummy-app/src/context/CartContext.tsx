// CartContext — lightweight cart state (item ids + quantities).
// In-memory only; cleared on page reload. No persistence — this is a fixture.
import React, { createContext, useContext, useState } from "react";

interface CartEntry {
  itemId: number;
  name: string;
  quantity: number;
  price: number;
}

interface CartContextValue {
  entries: CartEntry[];
  addToCart: (entry: CartEntry) => void;
  removeFromCart: (itemId: number) => void;
  updateQuantity: (itemId: number, quantity: number) => void;
  clearCart: () => void;
  total: number;
}

const CartContext = createContext<CartContextValue | null>(null);

export function CartProvider({ children }: { children: React.ReactNode }) {
  const [entries, setEntries] = useState<CartEntry[]>([]);

  const addToCart = (entry: CartEntry) => {
    setEntries((prev) => {
      const existing = prev.find((e) => e.itemId === entry.itemId);
      if (existing) {
        return prev.map((e) =>
          e.itemId === entry.itemId
            ? { ...e, quantity: e.quantity + entry.quantity }
            : e
        );
      }
      return [...prev, entry];
    });
  };

  const removeFromCart = (itemId: number) => {
    setEntries((prev) => prev.filter((e) => e.itemId !== itemId));
  };

  const updateQuantity = (itemId: number, quantity: number) => {
    if (quantity <= 0) {
      removeFromCart(itemId);
    } else {
      setEntries((prev) =>
        prev.map((e) => (e.itemId === itemId ? { ...e, quantity } : e))
      );
    }
  };

  const clearCart = () => setEntries([]);

  const total = entries.reduce((sum, e) => sum + e.price * e.quantity, 0);

  return (
    <CartContext.Provider
      value={{ entries, addToCart, removeFromCart, updateQuantity, clearCart, total }}
    >
      {children}
    </CartContext.Provider>
  );
}

export function useCart(): CartContextValue {
  const ctx = useContext(CartContext);
  if (!ctx) throw new Error("useCart must be used within CartProvider");
  return ctx;
}
