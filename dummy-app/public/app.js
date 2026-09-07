// Deliberately plain vanilla JS — this app exists to be tested, not to demonstrate a frontend
// framework. Note: the delete button below intentionally has NO data-testid, so the
// qa-locator-explorer role has a real element to tag "role-fallback" (docs §1.4/§3.6).

const loginSection = document.getElementById("login-section");
const itemsSection = document.getElementById("items-section");
const loginForm = document.getElementById("login-form");
const loginError = document.getElementById("login-error");
const addItemForm = document.getElementById("add-item-form");
const itemList = document.getElementById("item-list");
const logoutButton = document.getElementById("logout-button");
const searchInput = document.getElementById("search-input");
const sortButton = document.getElementById("sort-button");
const confirmModal = document.getElementById("confirm-modal");
const confirmDeleteBtn = document.getElementById("confirm-delete");
const cancelDeleteBtn = document.getElementById("cancel-delete");
const toastContainer = document.getElementById("toast-container");

let itemToDelete = null;
let isSorted = false;

function showToast(message) {
  toastContainer.textContent = message;
  toastContainer.style.display = "block";
  setTimeout(() => {
    toastContainer.style.display = "none";
  }, 3000);
}

async function loadItems() {
  const q = searchInput.value;
  const res = await fetch(`/api/items${q ? `?q=${encodeURIComponent(q)}` : ''}`);
  let items = await res.json();
  
  if (isSorted) {
    items.sort((a, b) => a.name.localeCompare(b.name));
  }
  
  itemList.innerHTML = "";
  for (const item of items) {
    const li = document.createElement("li");
    
    const nameSpan = document.createElement("span");
    nameSpan.textContent = item.name + " ";
    nameSpan.style.cursor = "pointer";
    nameSpan.title = "Click to edit";
    
    nameSpan.addEventListener("click", () => {
      const input = document.createElement("input");
      input.value = item.name;
      li.insertBefore(input, nameSpan);
      li.removeChild(nameSpan);
      input.focus();
      
      const saveEdit = async () => {
        const newName = input.value;
        if (newName && newName !== item.name) {
          await fetch(`/api/items/${item.id}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: newName }),
          });
          showToast("Item updated");
        }
        loadItems();
      };
      
      input.addEventListener("blur", saveEdit);
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          input.blur();
        }
      });
    });
    li.appendChild(nameSpan);

    const del = document.createElement("button");
    del.textContent = "Delete"; // NO data-testid on purpose — see comment above
    del.addEventListener("click", () => {
      itemToDelete = item.id;
      confirmModal.style.display = "block";
    });
    li.appendChild(del);
    itemList.appendChild(li);
  }
}

loginForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const email = document.getElementById("email").value;
  const password = document.getElementById("password").value;
  const res = await fetch("/api/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    loginError.hidden = false;
    loginError.textContent = "Invalid credentials";
    return;
  }
  loginSection.hidden = true;
  itemsSection.hidden = false;
  loadItems();
});

addItemForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = document.getElementById("item-name");
  const name = input.value;
  if (!name) return;
  await fetch("/api/items", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  input.value = "";
  showToast("Item added");
  loadItems();
});

logoutButton.addEventListener("click", async () => {
  await fetch("/api/logout", { method: "POST" });
  loginSection.hidden = false;
  itemsSection.hidden = true;
});

searchInput.addEventListener("input", () => {
  loadItems();
});

sortButton.addEventListener("click", () => {
  isSorted = !isSorted;
  loadItems();
});

confirmDeleteBtn.addEventListener("click", async () => {
  if (itemToDelete) {
    await fetch(`/api/items/${itemToDelete}`, { method: "DELETE" });
    itemToDelete = null;
    confirmModal.style.display = "none";
    showToast("Item deleted");
    loadItems();
  }
});

cancelDeleteBtn.addEventListener("click", () => {
  itemToDelete = null;
  confirmModal.style.display = "none";
});
