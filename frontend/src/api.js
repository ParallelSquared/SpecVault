// Single source of truth for the backend address.
// Override per-environment with VITE_API_BASE in a .env file; see .env.example.
export const API_BASE =
  import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000';

export const libraryUrl = (path = '') => `${API_BASE}/libraries/${path}`;
