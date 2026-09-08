// PriceDisplay — leaf of the 3-deep transitive import chain:
//   PriceDisplay  ←  CartButton  ←  ProductList  (←  ItemsPage and OrdersPage)
// Catalog 2 §2.2 point 2: changing PriceDisplay must trace up two hops to a route.
// Also imported directly by CartPage — the dual-path case (§2.2 point 3).
import React from "react";

interface PriceDisplayProps {
  price: number;
  label?: string;
}

export function PriceDisplay({ price, label = "Price" }: PriceDisplayProps) {
  return (
    <span data-testid="price-display">
      {label}: ${price.toFixed(2)}
    </span>
  );
}
