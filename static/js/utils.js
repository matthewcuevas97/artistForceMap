import { GENRE_HUE, SPOTIFY_SVG, YOUTUBE_SVG, APPLE_SVG } from './constants.js';
import { nodeScale, showSimilarity, showGenre } from './state.js';

export function escapeHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function nodeRadius(d) {
  return (4 + d.score * 20) * nodeScale;
}

export function nodeColor(d) {
  const hue = GENRE_HUE[d.genre] ?? 220;
  const sat = 20 + d.score * 70;
  const lit  = 25 + d.score * 35;
  return `hsl(${hue}, ${sat.toFixed(1)}%, ${lit.toFixed(1)}%)`;
}

export function labelOpacity(d) {
  if (d.score < 0.1) return 0;
  return Math.min(1.0, 0.15 + d.score * 0.85);
}

export function edgeBaseOpacity(e) {
  if (e.type === "similarity" && !showSimilarity) return 0;
  if (e.type === "genre"      && !showGenre)      return 0;
  return 0.08;
}

export function buildServiceLinks(artist, trackName, btnClass, svgSize) {
  const enc = encodeURIComponent;
  const a   = enc(artist);
  const n   = enc(trackName);
  const sz  = svgSize || 18;
  const spotifySvg = SPOTIFY_SVG.replace('width:18px;height:18px', `width:${sz}px;height:${sz}px`);
  const youtubeSvg = YOUTUBE_SVG.replace('width:18px;height:18px', `width:${sz}px;height:${sz}px`);
  const appleSvg   = APPLE_SVG.replace('width:18px;height:18px',   `width:${sz}px;height:${sz}px`);
  return (
    `<a href="https://open.spotify.com/search/${a}%20${n}" target="_blank" class="${btnClass}">${spotifySvg}</a>` +
    `<a href="https://music.youtube.com/search?q=${a}+${n}" target="_blank" class="${btnClass}">${youtubeSvg}</a>` +
    `<a href="https://music.apple.com/search?term=${a}+${n}" target="_blank" class="${btnClass}">${appleSvg}</a>`
  );
}
