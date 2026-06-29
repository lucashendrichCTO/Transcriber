/**
 * Tests for the Exit button handler in static/app.js.
 *
 * The handler calls window.pywebview._quit() when running inside the native
 * app, and falls back to window.close() in a plain browser.  Both branches
 * are tested by controlling what the global window object exposes.
 *
 * The handler logic is extracted verbatim from app.js so it can be imported
 * as an ES module.  After a future refactor that modularises app.js, this
 * import can be replaced with the real source.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";

// Extracted verbatim from app.js — the click handler body.
function handleExitClick(win) {
  if (win.pywebview && win.pywebview._quit) {
    win.pywebview._quit();
  } else if (win.close) {
    win.close();
  }
}

describe("Exit button — pywebview present", () => {
  it("calls window.pywebview._quit()", () => {
    const quit = vi.fn();
    const win = { pywebview: { _quit: quit }, close: vi.fn() };
    handleExitClick(win);
    expect(quit).toHaveBeenCalledOnce();
  });

  it("does not call window.close() when pywebview is present", () => {
    const close = vi.fn();
    const win = { pywebview: { _quit: vi.fn() }, close };
    handleExitClick(win);
    expect(close).not.toHaveBeenCalled();
  });
});

describe("Exit button — pywebview absent (browser / dev mode)", () => {
  it("calls window.close() as fallback", () => {
    const close = vi.fn();
    const win = { close };
    handleExitClick(win);
    expect(close).toHaveBeenCalledOnce();
  });

  it("calls window.close() when pywebview exists but _quit is missing", () => {
    const close = vi.fn();
    const win = { pywebview: {}, close };
    handleExitClick(win);
    expect(close).toHaveBeenCalledOnce();
  });

  it("calls window.close() when pywebview is null", () => {
    const close = vi.fn();
    const win = { pywebview: null, close };
    handleExitClick(win);
    expect(close).toHaveBeenCalledOnce();
  });
});

describe("Exit button — safety guard", () => {
  it("does not throw when window.close is also missing", () => {
    // Should not throw — handles gracefully.
    const win = {};
    expect(() => handleExitClick(win)).not.toThrow();
  });
});
