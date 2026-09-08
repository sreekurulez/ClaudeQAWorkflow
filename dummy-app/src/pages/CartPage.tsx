// CartPage — /cart route.
// Imports Header (shared component) and CartButton directly (dual-path for PriceDisplay).
// Also imports PriceDisplay directly for the cart total — this is the dual-path case:
//   CartPage → PriceDisplay  (direct path)
//   CartPage → CartButton → PriceDisplay  (transitive path)
// Both paths must be unioned by the reverse import graph (§2.2 point 3).
import React from "react";
import { Link, useNavigate } from "react-router-dom";
import { Header } from "../components/Header";
import { CartButton } from "../components/CartButton";
import { PriceDisplay } from "../components/PriceDisplay";
import { useCart } from "../context/CartContext";
import { useAuth } from "../context/AuthContext";
import { useEffect } from "react";

export function CartPage() {
  const { entries, removeFromCart, updateQuantity, clearCart, total } = useCart();
  const { isAuthenticated } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (!isAuthenticated) navigate("/login");
  }, [isAuthenticated, navigate]);

  return (
    <section>
      <Header title="Cart" />
      {entries.length === 0 ? (
        <p data-testid="cart-empty-message">Your cart is empty.</p>
      ) : (
        <>
          <ul data-testid="cart-item-list">
            {entries.map((entry) => (
              <li key={entry.itemId} data-testid={`cart-entry-${entry.itemId}`}>
                <span data-testid={`cart-entry-name-${entry.itemId}`}>
                  {entry.name}
                </span>
                {" "}
                <PriceDisplay price={entry.price} label="Unit price" />
                {" "}
                <input
                  type="number"
                  data-testid={`cart-entry-qty-${entry.itemId}`}
                  value={entry.quantity}
                  min={1}
                  onChange={(e) =>
                    updateQuantity(entry.itemId, Number(e.target.value))
                  }
                />
                <button
                  data-testid={`cart-remove-${entry.itemId}`}
                  onClick={() => removeFromCart(entry.itemId)}
                >
                  Remove
                </button>
                <Link
                  to={`/cart/${entry.itemId}`}
                  data-testid={`cart-entry-detail-${entry.itemId}`}
                >
                  Details
                </Link>
                {/* CartButton imported directly here — dual-path case for PriceDisplay */}
                <CartButton
                  itemId={entry.itemId}
                  itemName={entry.name}
                  price={entry.price}
                />
              </li>
            ))}
          </ul>
          <div data-testid="cart-total">
            <PriceDisplay price={total} label="Total" />
          </div>
          <button
            data-testid="cart-checkout-button"
            onClick={() => {
              clearCart();
              alert("Order placed! (stub)");
            }}
          >
            Checkout
          </button>
          <button data-testid="cart-clear-button" onClick={clearCart}>
            Clear cart
          </button>
        </>
      )}
    </section>
  );
}
