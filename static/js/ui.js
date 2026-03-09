/**
 * ui.js — lightweight UI helpers that any module can import without circularity.
 * Controls (minimize/expand menu) live here so discovery.js can import them
 * without creating a cycle with controls.js.
 */

import { isMobile } from './state.js';

export function minimizeMenu() {
  const el  = document.getElementById("controls");
  const btn = document.getElementById("menuToggle");
  if (el)  el.classList.add("minimized");
  if (btn) btn.textContent = "+";
}

export function expandMenu() {
  const el  = document.getElementById("controls");
  const btn = document.getElementById("menuToggle");
  if (el)  el.classList.remove("minimized");
  if (btn) btn.textContent = "−";
}
