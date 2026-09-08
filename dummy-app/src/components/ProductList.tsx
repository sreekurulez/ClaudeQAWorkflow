// ProductList — root of the 3-deep transitive import chain:
//   PriceDisplay  ←  CartButton  ←  ProductList
// Imported by ItemsPage and OrdersPage, so changes to PriceDisplay
// must be traced through CartButton → ProductList → those two routes.
import React from "react";
import { CartButton } from "./CartButton";

export interface Item {
  id: number;
  name: string;
  price?: number;
}

interface ProductListProps {
  items: Item[];
  onDelete?: (id: number) => void;
  onEdit?: (id: number, newName: string) => void;
  showCartButton?: boolean;
}

export function ProductList({
  items,
  onDelete,
  onEdit,
  showCartButton = false,
}: ProductListProps) {
  return (
    <ul data-testid="item-list">
      {items.map((item) => (
        <li key={item.id} data-testid={`item-row-${item.id}`}>
          <span data-testid={`item-name-${item.id}`}>{item.name}</span>
          {showCartButton && item.price !== undefined && (
            <CartButton
              itemId={item.id}
              itemName={item.name}
              price={item.price}
            />
          )}
          {onEdit && (
            <button
              data-testid={`item-edit-${item.id}`}
              onClick={() => {
                const newName = window.prompt("New name:", item.name);
                if (newName && newName !== item.name) {
                  onEdit(item.id, newName);
                }
              }}
            >
              Edit
            </button>
          )}
          {onDelete && (
            // NO data-testid on purpose — locator-explorer must tag this role-fallback.
            // See context.md §Testability requirements and PROPOSED_DUMMY_APP_UPGRADE.md §2.3.
            <button onClick={() => onDelete(item.id)}>Delete</button>
          )}
        </li>
      ))}
    </ul>
  );
}
