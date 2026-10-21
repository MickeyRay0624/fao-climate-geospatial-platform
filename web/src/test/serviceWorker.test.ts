import { expect, it, vi } from "vitest";
import source from "../../public/sw.js?raw";

it.each([
  "/api/me",
  "/api/data/v1/versions/example/preview",
  "/api/apps/investment-prioritisation/v1/runs",
  "/objects/example",
  "/api/apps/extension-field-support/v1/media/example/view",
])("leaves sensitive requests outside the service-worker cache: %s", (path) => {
  const listeners = new Map<string, (event: unknown) => void>();
  const registerWorker = new Function("self", "URL", source);
  registerWorker({
    location: { origin: "https://platform.example.test" },
    addEventListener: (type: string, listener: (event: unknown) => void) => listeners.set(type, listener),
  }, URL);
  const respondWith = vi.fn();
  listeners.get("fetch")!({
    request: { url: `https://platform.example.test${path}`, method: "GET", mode: "cors" },
    respondWith,
  });

  expect(respondWith).not.toHaveBeenCalled();
});
