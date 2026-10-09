const apiBase = (window.ELIMU_API_URL || "http://127.0.0.1:8000/api").replace(/\/$/, "");

export async function apiRequest(path, options = {}) {
  const response = await fetch(`${apiBase}${path}`, {
    ...options,
    credentials: "include",
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
  });
  const payload = response.status === 204 ? {} : await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) {
      window.dispatchEvent(new CustomEvent("elimu:unauthorized"));
    }
    throw new Error(payload.error || `Request failed (${response.status}).`);
  }
  return payload;
}

export function showApiError(target, error) {
  if (!target) return;
  target.textContent = error instanceof Error ? error.message : "Something went wrong. Please try again.";
  target.classList.remove("hidden");
}
