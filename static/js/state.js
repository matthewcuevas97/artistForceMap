import { THRESHOLD_LEVELS, DRAWER_PEEK_H } from './constants.js';

// ── Raw data (never mutated after fetch) ──────────────────────────────────────
export let rawNodes = [];
export let rawEdges = [];
export let allEdgesForFrontier = [];
export let frontierEdgesLoaded = false;
export let userSeeds = new Set();

// ── Simulation working copies ─────────────────────────────────────────────────
export let simNodes = [];
export let simEdges = [];

// ── Control state ─────────────────────────────────────────────────────────────
export let nodeScale      = 1.0;
export let edgeThreshold  = THRESHOLD_LEVELS[2];
export let showSimilarity = true;
export let showGenre      = true;
export let dayFilter      = "ALL";

// ── Discovery mode ────────────────────────────────────────────────────────────
export let discoveryMode    = false;
export let discovered       = new Set();
export let fringe           = new Set();
export let subgraph         = new Set();
export let ambassadors      = new Set();
export let lastDiscovered   = null;

// ── Selection / panel ─────────────────────────────────────────────────────────
export let openArtistName = null;
export let pinnedDatum    = null;
export let panelRequestId = 0;
export let drawerState    = 'hidden';
export let drawerRequestId   = 0;
export let drawerArtistName  = null;
export let drawerTracks      = [];
export let drawerExpandedIdx = null;

// ── Subgraph highlight ────────────────────────────────────────────────────────
export let isSubgraphHighlight   = false;
export let highlightNeighborhood = null;  // Set<name>

// ── Audio / playlist ──────────────────────────────────────────────────────────
export let currentAudio    = null;
export let currentPlayBtn  = null;
export let currentTracks   = [];
export let expandedTrackIndex = null;
export let playlist        = [];

// ── Misc ──────────────────────────────────────────────────────────────────────
export let dragMoved = false;
export let thresholdDebounce = null;
export let controlsCollapsedBottom = 0;

// ── Viewport ──────────────────────────────────────────────────────────────────
export const W = window.innerWidth;
export const H = window.innerHeight;

export const isMobile = window.innerWidth < 768 || ('ontouchstart' in window);

export const drawerCollapsedH = () => Math.round(window.innerHeight * 0.45);
export const drawerExpandedH  = () => Math.round(window.innerHeight * 0.85);

// ── Setters (used by modules that need to mutate shared state) ─────────────────
export function setRawNodes(v)              { rawNodes = v; }
export function setRawEdges(v)              { rawEdges = v; }
export function setSimNodes(v)              { simNodes = v; }
export function setSimEdges(v)              { simEdges = v; }
export function setAllEdgesForFrontier(v)   { allEdgesForFrontier = v; }
export function setFrontierEdgesLoaded(v)   { frontierEdgesLoaded = v; }
export function setUserSeeds(v)             { userSeeds = v; }
export function setNodeScale(v)             { nodeScale = v; }
export function setEdgeThreshold(v)         { edgeThreshold = v; }
export function setShowSimilarity(v)        { showSimilarity = v; }
export function setShowGenre(v)             { showGenre = v; }
export function setDayFilter(v)             { dayFilter = v; }
export function setDiscoveryMode(v)         { discoveryMode = v; }
export function setLastDiscovered(v)        { lastDiscovered = v; }
export function setOpenArtistName(v)        { openArtistName = v; }
export function setPinnedDatum(v)           { pinnedDatum = v; }
export function setPanelRequestId(v)        { panelRequestId = v; }
export function setDrawerState(v)           { drawerState = v; }
export function setDrawerRequestId(v)       { drawerRequestId = v; }
export function setDrawerArtistName(v)      { drawerArtistName = v; }
export function setDrawerTracks(v)          { drawerTracks = v; }
export function setDrawerExpandedIdx(v)     { drawerExpandedIdx = v; }
export function setIsSubgraphHighlight(v)   { isSubgraphHighlight = v; }
export function setHighlightNeighborhood(v) { highlightNeighborhood = v; }
export function setCurrentAudio(v)          { currentAudio = v; }
export function setCurrentPlayBtn(v)        { currentPlayBtn = v; }
export function setCurrentTracks(v)         { currentTracks = v; }
export function setExpandedTrackIndex(v)    { expandedTrackIndex = v; }
export function setDragMoved(v)             { dragMoved = v; }
export function setThresholdDebounce(v)     { thresholdDebounce = v; }
export function setControlsCollapsedBottom(v) { controlsCollapsedBottom = v; }
