// Barrel file — re-exports all shared components.
// Catalog 2 §2.2 point 4: a barrel file can degenerate a reverse import graph into
// "everything affects everything." The indexer's handling of this must be tested
// against the fixture, not discovered first on finbook.
export * from "./Header";
export * from "./PriceDisplay";
export * from "./CartButton";
export * from "./ProductList";
export * from "./ConfirmDialog";
export * from "./Toast";
