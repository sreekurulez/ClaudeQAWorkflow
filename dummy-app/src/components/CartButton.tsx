// CartButton — middle of the 3-deep transitive import chain:
//   PriceDisplay  ←  CartButton  ←  ProductList
// Also imported directly by CartPage, creating the dual-path case (§2.2 point 3):
//   CartPage → CartButton → PriceDisplay  (one path)
//   CartPage → CartButton                 (another direct path)
import React from "react";
import { PriceDisplay } from "./PriceDisplay";
import { useCart } from "../context/CartContext";

interface CartButtonProps {
  itemId: number;
  itemName: string;
  price: number;
}

export function CartButton({ itemId, itemName, price }: CartButtonProps) {
  const { addToCart } = useCart();

  const handleAdd = () => {
    addToCart({ itemId, name: itemName, quantity: 1, price });
  };

  return (
    <span>
      <PriceDisplay price={price} />
      {" "}
      <button data-testid={`cart-add-${itemId}`} onClick={handleAdd}>
        Add to cart
      </button>
    </span>
  );
}
