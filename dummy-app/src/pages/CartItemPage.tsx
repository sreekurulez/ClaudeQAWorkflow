// CartItemPage — /cart/:itemId route (nested URL parameter under /cart layout).
import React from "react";
import { useParams, Link } from "react-router-dom";
import { useCart } from "../context/CartContext";

export function CartItemPage() {
  const { itemId } = useParams<{ itemId: string }>();
  const { entries, updateQuantity, removeFromCart } = useCart();

  const entry = entries.find((e) => String(e.itemId) === itemId);

  if (!entry) {
    return (
      <div>
        <p data-testid="cart-item-not-found">Item not in cart.</p>
        <Link to="/cart" data-testid="cart-item-back">
          ← Back to cart
        </Link>
      </div>
    );
  }

  return (
    <div>
      <h2 data-testid="cart-item-name">{entry.name}</h2>
      <p>Unit price: ${entry.price.toFixed(2)}</p>
      <label htmlFor="cart-item-qty">Quantity</label>
      <input
        id="cart-item-qty"
        type="number"
        data-testid="cart-item-quantity"
        value={entry.quantity}
        min={1}
        onChange={(e) => updateQuantity(entry.itemId, Number(e.target.value))}
      />
      <button
        data-testid="cart-item-remove-button"
        onClick={() => removeFromCart(entry.itemId)}
      >
        Remove from cart
      </button>
      <Link to="/cart" data-testid="cart-item-back">
        ← Back to cart
      </Link>
    </div>
  );
}
