import { apiRequest, showApiError } from "./api.js";

const form = document.querySelector("#login-form");
const submit = document.querySelector("#login-submit");
const error = document.querySelector("#login-error");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  error.classList.add("hidden");
  submit.disabled = true;
  submit.textContent = "Signing in…";
  const values = Object.fromEntries(new FormData(form).entries());
  try {
    await apiRequest("/auth/login", { method: "POST", body: JSON.stringify(values) });
    window.location.href = "./dashboard.html";
  } catch (reason) {
    showApiError(error, reason);
    submit.disabled = false;
    submit.textContent = "Sign in";
  }
});