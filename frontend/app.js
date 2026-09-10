/**
 * Musify — Music & Playlist Downloader - Modern Frontend Controller
 * Features:
 * - Native Windows Folder Picker via Backend Dialog
 * - Local HQ Full-Track Streaming & Preview Mini-Player
 * - Automatic Clipboard Detection on Window Focus
 * - 1-Click "Retry Failed Tracks" with auto-isolation
 * - Smart Filter Chips (All, Selected, Unselected, Downloaded, Failed)
 * - Progressive 60 FPS Chunked Rendering (50-item batches)
 * - Shift-Click Multi-Range Selection
 * - Live Queue Drawer & Real-Time Speedometer/ETA
 */

// Application State
const state = {
  currentPlaylist: null,
  selectedTrackIds: new Set(),
  failedTrackIds: new Set(),
  downloadedFilesMap: new Map(), // track_id -> filepath
  activeFilterChip: "all",
  defaultOutputDir: "",
  currentOutputDir: "",
  isDownloading: false,
  eventSource: null,
  currentlyPlayingId: null,
  isPlayingHQ: false,
  previewDuration: 30, // Default preview clip length

  // Progressive Rendering & Performance
  filteredTracks: [],
  renderedTrackCount: 0,
  batchSize: 50,
  lastCheckedIndex: -1,
  activeDownloadsMap: new Map(), // track_id -> { track_id, title, artists, status, message, cover_url }
  recentStorageKey: "musify_recent_v1",
  observer: null,
  lastClipboardChecked: "",
  publicUrl: "",
};

// DOM Elements
const elements = {
  fetchForm: document.getElementById("fetch-form"),
  playlistUrlInput: document.getElementById("playlist-url"),
  btnPasteClipboard: document.getElementById("btn-paste-clipboard"),
  btnClearUrl: document.getElementById("btn-clear-url"),
  btnFetch: document.getElementById("btn-fetch"),
  fetchSpinner: document.getElementById("fetch-spinner"),
  ffmpegBadge: document.getElementById("ffmpeg-badge"),
  ffmpegStatusText: document.getElementById("ffmpeg-status-text"),
  publicUrlBadge: document.getElementById("public-url-badge"),
  publicUrlText: document.getElementById("public-url-text"),
  btnCopyPublicUrl: document.getElementById("btn-copy-public-url"),

  // Auto-Clipboard Banner
  clipboardBanner: document.getElementById("clipboard-banner"),
  clipboardUrlPreview: document.getElementById("clipboard-url-preview"),
  btnClipboardLoad: document.getElementById("btn-clipboard-load"),
  btnClipboardDismiss: document.getElementById("btn-clipboard-dismiss"),

  // Recent Playlists
  recentSection: document.getElementById("recent-section"),
  recentGrid: document.getElementById("recent-grid"),
  btnClearRecent: document.getElementById("btn-clear-recent"),

  // Skeleton Loading Section
  skeletonSection: document.getElementById("skeleton-section"),

  // Settings
  btnSettingsToggle: document.getElementById("btn-settings-toggle"),
  settingsPanel: document.getElementById("settings-panel"),
  btnCloseSettings: document.getElementById("btn-close-settings"),
  settingOutdir: document.getElementById("setting-outdir"),
  btnBrowseFolder: document.getElementById("btn-browse-folder"),
  btnOpenDir: document.getElementById("btn-open-dir"),
  settingFormat: document.getElementById("setting-format"),
  settingBitrate: document.getElementById("setting-bitrate"),
  settingNaming: document.getElementById("setting-naming"),
  settingConcurrency: document.getElementById("setting-concurrency"),
  toggleM3u8: document.getElementById("toggle-m3u8"),
  toggleArtwork: document.getElementById("toggle-artwork"),
  toggleOverwrite: document.getElementById("toggle-overwrite"),

  // Playlist View
  playlistSection: document.getElementById("playlist-section"),
  plCover: document.getElementById("pl-cover"),
  plType: document.getElementById("pl-type"),
  plTitle: document.getElementById("pl-title"),
  plDesc: document.getElementById("pl-desc"),
  plAuthor: document.getElementById("pl-author"),
  plCount: document.getElementById("pl-count"),
  plDuration: document.getElementById("pl-duration"),
  qualityPills: document.getElementById("quality-pills"),
  btnStartDownload: document.getElementById("btn-start-download"),
  btnRetryFailed: document.getElementById("btn-retry-failed"),
  plFailedCount: document.getElementById("pl-failed-count"),
  downloadBtnLabel: document.getElementById("download-btn-label"),
  btnOpenFolder: document.getElementById("btn-open-folder"),
  btnSelectAll: document.getElementById("btn-select-all"),
  btnDeselectAll: document.getElementById("btn-deselect-all"),
  btnInvertSelect: document.getElementById("btn-invert-select"),
  selectionSummaryPill: document.getElementById("selection-summary-pill"),
  checkAll: document.getElementById("check-all"),
  tracksList: document.getElementById("tracks-list"),
  tracksSentinel: document.getElementById("tracks-sentinel"),
  btnLoadMore: document.getElementById("btn-load-more"),

  // In-Playlist Filter Bar & Chips
  trackFilterInput: document.getElementById("track-filter-input"),
  btnClearFilter: document.getElementById("btn-clear-filter"),
  filterCounter: document.getElementById("filter-counter"),
  filterQuickChips: document.getElementById("filter-quick-chips"),
  chipAllCount: document.getElementById("chip-all-count"),
  chipSelectedCount: document.getElementById("chip-selected-count"),
  chipUnselectedCount: document.getElementById("chip-unselected-count"),
  chipDoneCount: document.getElementById("chip-done-count"),
  chipFailedCount: document.getElementById("chip-failed-count"),

  // Expandable Queue Drawer
  queueDrawer: document.getElementById("queue-drawer"),
  queueActiveCount: document.getElementById("queue-active-count"),
  btnCloseQueue: document.getElementById("btn-close-queue"),
  queueItemsContainer: document.getElementById("queue-items-container"),
  queueEmptyMsg: document.getElementById("queue-empty-msg"),

  // Floating Download Bar & Live Metrics
  downloadBar: document.getElementById("download-bar"),
  barStatusText: document.getElementById("bar-status-text"),
  barProgressText: document.getElementById("bar-progress-text"),
  barProgressFill: document.getElementById("bar-progress-fill"),
  barSpeedVal: document.getElementById("bar-speed-val"),
  barEtaVal: document.getElementById("bar-eta-val"),
  barStreamsVal: document.getElementById("bar-streams-val"),
  btnBarToggleQueue: document.getElementById("btn-bar-toggle-queue"),
  btnQueueCount: document.getElementById("btn-queue-count"),
  btnBarOpenFolder: document.getElementById("btn-bar-open-folder"),
  btnBarCancel: document.getElementById("btn-bar-cancel"),

  // Floating Audio Preview / HQ Mini-Player
  miniPlayer: document.getElementById("mini-player"),
  mpCover: document.getElementById("mp-cover"),
  mpTitle: document.getElementById("mp-title"),
  mpQualityBadge: document.getElementById("mp-quality-badge"),
  mpArtist: document.getElementById("mp-artist"),
  mpBtnPlay: document.getElementById("mp-btn-play"),
  mpProgressBar: document.getElementById("mp-progress-bar"),
  mpProgressFill: document.getElementById("mp-progress-fill"),
  mpCurrentTime: document.getElementById("mp-current-time"),
  mpTotalTime: document.getElementById("mp-total-time"),
  mpBtnMute: document.getElementById("mp-btn-mute"),
  mpVolume: document.getElementById("mp-volume"),
  mpBtnClose: document.getElementById("mp-btn-close"),
  equalizerBars: document.getElementById("equalizer-bars"),
  previewPlayer: document.getElementById("audio-preview-player"),

  // Celebration Modal
  completionModal: document.getElementById("completion-modal"),
  modalSummaryText: document.getElementById("modal-summary-text"),
  modalStatCount: document.getElementById("modal-stat-count"),
  modalStatTime: document.getElementById("modal-stat-time"),
  modalStatFailures: document.getElementById("modal-stat-failures"),
  btnModalRetryFailed: document.getElementById("btn-modal-retry-failed"),
  modalFailedCount: document.getElementById("modal-failed-count"),
  btnModalOpenFolder: document.getElementById("btn-modal-open-folder"),
  btnModalClose: document.getElementById("btn-modal-close"),

  // Toasts
  toastContainer: document.getElementById("toast-container"),
};

// Initialize Application
document.addEventListener("DOMContentLoaded", () => {
  if (window.lucide) {
    window.lucide.createIcons();
  }
  loadSystemInfo();
  setupEventListeners();
  setupAudioPlayer();
  setupQualityPills();
  setupFilterChips();
  setupIntersectionObserver();
  setupKeyboardShortcuts();
  loadRecentPlaylists();
  setupClipboardAutoDetect();
});

// Toast Notification Helper
function showToast(message, type = "success", duration = 3500) {
  if (!elements.toastContainer) return;
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  let iconName = "check-circle-2";
  if (type === "error") iconName = "alert-circle";
  if (type === "info") iconName = "info";

  toast.innerHTML = `<i data-lucide="${iconName}"></i> <span>${escapeHtml(message)}</span>`;
  elements.toastContainer.appendChild(toast);
  if (window.lucide) window.lucide.createIcons();

  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateX(40px)";
    setTimeout(() => toast.remove(), 250);
  }, duration);
}

// Load System & FFmpeg Info
async function loadSystemInfo() {
  try {
    const res = await fetch("/api/system/info");
    const data = await res.json();
    state.defaultOutputDir = data.default_music_dir || "";
    if (elements.settingOutdir) elements.settingOutdir.value = state.defaultOutputDir;

    if (data.ffmpeg_ready) {
      elements.ffmpegBadge.className = "status-pill ready";
      elements.ffmpegStatusText.textContent = "FFmpeg Engine Ready";
    } else {
      elements.ffmpegBadge.className = "status-pill";
      elements.ffmpegStatusText.textContent = "FFmpeg Loading...";
    }

    if (data.public_url) {
      state.publicUrl = data.public_url;
      if (elements.publicUrlBadge) {
        elements.publicUrlBadge.classList.remove("hidden");
        elements.publicUrlBadge.title = `Access from anywhere: ${data.public_url}`;
      }
    } else {
      // Re-check once after 4s if tunnel was initializing
      setTimeout(async () => {
        try {
          const r = await fetch("/api/system/info");
          const d = await r.json();
          if (d.public_url && elements.publicUrlBadge) {
            state.publicUrl = d.public_url;
            elements.publicUrlBadge.classList.remove("hidden");
            elements.publicUrlBadge.title = `Access from anywhere: ${d.public_url}`;
          }
        } catch (_) {}
      }, 4000);
    }
  } catch (err) {
    console.error("Failed to load system info:", err);
  }
}

// Event Listeners Setup
function setupEventListeners() {
  // Input clear and paste button visibility
  elements.playlistUrlInput.addEventListener("input", () => {
    const hasVal = elements.playlistUrlInput.value.trim().length > 0;
    if (hasVal) {
      elements.btnClearUrl.classList.remove("hidden");
      if (elements.btnPasteClipboard) elements.btnPasteClipboard.classList.add("hidden");
    } else {
      elements.btnClearUrl.classList.add("hidden");
      if (elements.btnPasteClipboard) elements.btnPasteClipboard.classList.remove("hidden");
    }
  });

  elements.btnClearUrl.addEventListener("click", () => {
    elements.playlistUrlInput.value = "";
    elements.btnClearUrl.classList.add("hidden");
    if (elements.btnPasteClipboard) elements.btnPasteClipboard.classList.remove("hidden");
    elements.playlistUrlInput.focus();
  });

  // Paste from Clipboard Button
  if (elements.btnPasteClipboard) {
    elements.btnPasteClipboard.addEventListener("click", pasteFromClipboard);
  }

  // Copy Public Live URL Button
  if (elements.btnCopyPublicUrl) {
    elements.btnCopyPublicUrl.addEventListener("click", (e) => {
      e.stopPropagation();
      if (state.publicUrl) {
        navigator.clipboard.writeText(state.publicUrl);
        showToast("🌐 Public HTTPS link copied! Access from your phone or anywhere.", "success", 4000);
      }
    });
  }

  // Example Chips
  document.querySelectorAll(".btn-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      const url = btn.getAttribute("data-url");
      elements.playlistUrlInput.value = url;
      elements.btnClearUrl.classList.remove("hidden");
      if (elements.btnPasteClipboard) elements.btnPasteClipboard.classList.add("hidden");
      elements.fetchForm.requestSubmit();
    });
  });

  // Clear Recent Playlists
  if (elements.btnClearRecent) {
    elements.btnClearRecent.addEventListener("click", clearRecentPlaylists);
  }

  // Form Submit -> Fetch Metadata
  elements.fetchForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const url = elements.playlistUrlInput.value.trim();
    if (!url) return;
    hideClipboardBanner();
    await fetchPlaylistData(url);
  });

  // Settings Panel Toggle
  elements.btnSettingsToggle.addEventListener("click", () => {
    elements.settingsPanel.classList.toggle("hidden");
  });
  elements.btnCloseSettings.addEventListener("click", () => {
    elements.settingsPanel.classList.add("hidden");
  });

  // Windows Native Folder Picker
  if (elements.btnBrowseFolder) {
    elements.btnBrowseFolder.addEventListener("click", chooseFolderNative);
  }

  // Browse Directory in Windows Explorer
  elements.btnOpenDir.addEventListener("click", openCurrentDirectory);
  elements.btnOpenFolder.addEventListener("click", openCurrentDirectory);
  elements.btnBarOpenFolder.addEventListener("click", openCurrentDirectory);

  // Select / Deselect Controls
  elements.btnSelectAll.addEventListener("click", () => setAllTracksSelection(true));
  elements.btnDeselectAll.addEventListener("click", () => setAllTracksSelection(false));
  if (elements.btnInvertSelect) {
    elements.btnInvertSelect.addEventListener("click", invertTracksSelection);
  }
  elements.checkAll.addEventListener("change", (e) => setAllTracksSelection(e.target.checked));

  // In-Playlist Filter Listener
  if (elements.trackFilterInput) {
    elements.trackFilterInput.addEventListener("input", filterTracks);
  }
  if (elements.btnClearFilter) {
    elements.btnClearFilter.addEventListener("click", () => {
      elements.trackFilterInput.value = "";
      filterTracks();
      elements.trackFilterInput.focus();
    });
  }

  // Load More Tracks Button (manual fallback for sentinel)
  if (elements.btnLoadMore) {
    elements.btnLoadMore.addEventListener("click", renderNextTrackBatch);
  }

  // Live Queue Drawer Toggle & Close
  if (elements.btnBarToggleQueue) {
    elements.btnBarToggleQueue.addEventListener("click", () => {
      elements.queueDrawer.classList.toggle("hidden");
    });
  }
  if (elements.btnCloseQueue) {
    elements.btnCloseQueue.addEventListener("click", () => {
      elements.queueDrawer.classList.add("hidden");
    });
  }

  // Start Download
  elements.btnStartDownload.addEventListener("click", startDownloadProcess);

  // Retry Failed Buttons
  if (elements.btnRetryFailed) {
    elements.btnRetryFailed.addEventListener("click", retryFailedTracks);
  }
  if (elements.btnModalRetryFailed) {
    elements.btnModalRetryFailed.addEventListener("click", () => {
      elements.completionModal.classList.add("hidden");
      retryFailedTracks();
    });
  }

  // Cancel Download
  elements.btnBarCancel.addEventListener("click", cancelDownloadProcess);

  // Celebration Modal Close
  if (elements.btnModalClose) {
    elements.btnModalClose.addEventListener("click", () => {
      elements.completionModal.classList.add("hidden");
    });
  }
  if (elements.btnModalOpenFolder) {
    elements.btnModalOpenFolder.addEventListener("click", () => {
      openCurrentDirectory();
      elements.completionModal.classList.add("hidden");
    });
  }

  // Completion Modal Backdrop Click to dismiss
  if (elements.completionModal) {
    elements.completionModal.addEventListener("click", (e) => {
      if (e.target === elements.completionModal) {
        elements.completionModal.classList.add("hidden");
      }
    });
  }

  // Live sync of manual output directory edits
  if (elements.settingOutdir) {
    elements.settingOutdir.addEventListener("input", () => {
      const val = elements.settingOutdir.value.trim();
      if (val && state.currentPlaylist) {
        state.currentOutputDir = `${val}\\${sanitizeFilename(state.currentPlaylist.title)}`;
      }
    });
  }
}

// Native Windows Folder Picker
async function chooseFolderNative() {
  try {
    showToast("Opening Windows folder selector dialog...", "info", 2500);
    const initialDir = elements.settingOutdir.value.trim() || state.defaultOutputDir;
    const res = await fetch("/api/system/select-folder", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ initial_dir: initialDir }),
    });
    const data = await res.json();
    if (data.success && data.selected_dir) {
      elements.settingOutdir.value = data.selected_dir;
      if (state.currentPlaylist) {
        state.currentOutputDir = `${data.selected_dir}\\${sanitizeFilename(state.currentPlaylist.title)}`;
      }
      showToast(`Saved download destination: ${data.selected_dir}`, "success", 4000);
    }
  } catch (err) {
    showToast("Could not open Windows folder picker: " + err.message, "error");
  }
}

// Auto-Clipboard Detection Setup
function setupClipboardAutoDetect() {
  window.addEventListener("focus", checkClipboardForSpotifyLink);

  if (elements.btnClipboardLoad) {
    elements.btnClipboardLoad.addEventListener("click", () => {
      const url = elements.clipboardUrlPreview.textContent;
      if (url) {
        elements.playlistUrlInput.value = url;
        elements.btnClearUrl.classList.remove("hidden");
        if (elements.btnPasteClipboard) elements.btnPasteClipboard.classList.add("hidden");
        hideClipboardBanner();
        elements.fetchForm.requestSubmit();
      }
    });
  }

  if (elements.btnClipboardDismiss) {
    elements.btnClipboardDismiss.addEventListener("click", hideClipboardBanner);
  }
}

async function checkClipboardForSpotifyLink() {
  try {
    if (!navigator.clipboard || !navigator.clipboard.readText) return;
    const text = (await navigator.clipboard.readText()).trim();
    if (!text) return;

    const isSpotify = text.includes("open.spotify.com/") || text.startsWith("spotify:");
    if (isSpotify && text !== state.lastClipboardChecked && (!state.currentPlaylist || text !== elements.playlistUrlInput.value.trim())) {
      state.lastClipboardChecked = text;
      elements.clipboardUrlPreview.textContent = text;
      elements.clipboardBanner.classList.remove("hidden");
      if (window.lucide) window.lucide.createIcons();
    }
  } catch (err) {
    // Clipboard permission not granted yet - ignore quietly
  }
}

function hideClipboardBanner() {
  if (elements.clipboardBanner) {
    elements.clipboardBanner.classList.add("hidden");
  }
}

// Quick Filter Chips Setup
function setupFilterChips() {
  if (!elements.filterQuickChips) return;
  const chips = elements.filterQuickChips.querySelectorAll(".filter-chip");
  chips.forEach((chip) => {
    chip.addEventListener("click", () => {
      chips.forEach((c) => c.classList.remove("active"));
      chip.classList.add("active");
      state.activeFilterChip = chip.getAttribute("data-filter") || "all";
      filterTracks();
    });
  });
}

function updateFilterChipBadges() {
  if (!state.currentPlaylist) return;
  const total = state.currentPlaylist.tracks.length;
  const selected = state.selectedTrackIds.size;
  const unselected = total - selected;
  const downloaded = state.downloadedFilesMap.size;
  const failed = state.failedTrackIds.size;

  if (elements.chipAllCount) elements.chipAllCount.textContent = total;
  if (elements.chipSelectedCount) elements.chipSelectedCount.textContent = selected;
  if (elements.chipUnselectedCount) elements.chipUnselectedCount.textContent = unselected;
  if (elements.chipDoneCount) elements.chipDoneCount.textContent = downloaded;
  if (elements.chipFailedCount) elements.chipFailedCount.textContent = failed;

  // Show/Hide Retry button if there are failures
  if (elements.btnRetryFailed) {
    if (failed > 0) {
      elements.btnRetryFailed.classList.remove("hidden");
      if (elements.plFailedCount) elements.plFailedCount.textContent = failed;
    } else {
      elements.btnRetryFailed.classList.add("hidden");
    }
  }
}

// Recent Playlists Management
function loadRecentPlaylists() {
  if (!elements.recentSection || !elements.recentGrid) return;
  try {
    const raw = localStorage.getItem(state.recentStorageKey);
    const items = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(items) || items.length === 0) {
      elements.recentSection.classList.add("hidden");
      return;
    }

    elements.recentGrid.innerHTML = items
      .map(
        (pl) => `
        <div class="recent-card" data-url="${escapeHtml(pl.url)}" title="Reload ${escapeHtml(pl.title)}">
          <img src="${escapeHtml(pl.cover_url || '')}" class="recent-thumb" alt="" loading="lazy" />
          <div class="recent-info">
            <span class="recent-name">${escapeHtml(pl.title)}</span>
            <span class="recent-count">${pl.total_tracks} tracks • ${escapeHtml(pl.author || 'Spotify')}</span>
          </div>
        </div>
      `
      )
      .join("");

    // Bind click events to recent cards
    elements.recentGrid.querySelectorAll(".recent-card").forEach((card) => {
      card.addEventListener("click", () => {
        const url = card.getAttribute("data-url");
        if (url) {
          elements.playlistUrlInput.value = url;
          elements.btnClearUrl.classList.remove("hidden");
          if (elements.btnPasteClipboard) elements.btnPasteClipboard.classList.add("hidden");
          elements.fetchForm.requestSubmit();
        }
      });
    });

    elements.recentSection.classList.remove("hidden");
  } catch (err) {
    console.error("Failed loading recent playlists:", err);
  }
}

function saveRecentPlaylist(data, url) {
  try {
    const raw = localStorage.getItem(state.recentStorageKey);
    let items = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(items)) items = [];

    // Filter out duplicates with same url or id
    items = items.filter((item) => item.url !== url && item.id !== data.id);

    // Prepend new item
    items.unshift({
      id: data.id,
      title: data.title,
      author: data.author,
      cover_url: data.cover_url,
      total_tracks: data.total_tracks,
      url: url,
      timestamp: Date.now(),
    });

    // Cap at 6 items
    items = items.slice(0, 6);
    localStorage.setItem(state.recentStorageKey, JSON.stringify(items));
    loadRecentPlaylists();
  } catch (err) {
    console.error("Failed saving recent playlist:", err);
  }
}

function clearRecentPlaylists() {
  localStorage.removeItem(state.recentStorageKey);
  if (elements.recentSection) elements.recentSection.classList.add("hidden");
  showToast("Recent history cleared", "info", 2000);
}

// Quick Quality Pills Setup
function setupQualityPills() {
  if (!elements.qualityPills) return;
  const pills = elements.qualityPills.querySelectorAll(".pill-btn");
  pills.forEach((pill) => {
    pill.addEventListener("click", () => {
      pills.forEach((p) => p.classList.remove("active"));
      pill.classList.add("active");

      const format = pill.getAttribute("data-format");
      const bitrate = pill.getAttribute("data-bitrate");

      if (elements.settingFormat) elements.settingFormat.value = format;
      if (elements.settingBitrate) elements.settingBitrate.value = bitrate;

      showToast(`Audio format set to ${format.toUpperCase()} (${bitrate} kbps)`, "info", 2000);
    });
  });
}

// Keyboard Shortcuts Setup
function setupKeyboardShortcuts() {
  window.addEventListener("keydown", (e) => {
    const active = document.activeElement;
    const isTyping = active && (active.tagName === "INPUT" || active.tagName === "TEXTAREA" || active.isContentEditable);

    // '/' to focus search / filter
    if (e.key === "/" && !isTyping) {
      e.preventDefault();
      if (state.currentPlaylist && elements.trackFilterInput) {
        elements.trackFilterInput.focus();
      } else if (elements.playlistUrlInput) {
        elements.playlistUrlInput.focus();
      }
      return;
    }

    // Ctrl+A to select all (when not in input)
    if (e.ctrlKey && (e.key === "a" || e.key === "A") && !isTyping && state.currentPlaylist) {
      e.preventDefault();
      setAllTracksSelection(true);
      showToast("Selected all tracks", "info", 1500);
      return;
    }

    // Spacebar to toggle audio preview / HQ play
    if (e.code === "Space" && !isTyping && state.currentlyPlayingId) {
      e.preventDefault();
      if (elements.mpBtnPlay) elements.mpBtnPlay.click();
      return;
    }

    // Escape to close modals / queue
    if (e.key === "Escape") {
      if (elements.queueDrawer && !elements.queueDrawer.classList.contains("hidden")) {
        elements.queueDrawer.classList.add("hidden");
        return;
      }
      if (elements.settingsPanel && !elements.settingsPanel.classList.contains("hidden")) {
        elements.settingsPanel.classList.add("hidden");
        return;
      }
      if (elements.completionModal && !elements.completionModal.classList.contains("hidden")) {
        elements.completionModal.classList.add("hidden");
        return;
      }
      if (elements.previewPlayer && !elements.previewPlayer.paused) {
        elements.previewPlayer.pause();
        if (elements.miniPlayer) elements.miniPlayer.classList.add("hidden");
        resetRowPlayIcons();
      }
    }
  });
}

// Paste From Clipboard Helper
async function pasteFromClipboard() {
  try {
    const text = await navigator.clipboard.readText();
    if (text && text.trim()) {
      elements.playlistUrlInput.value = text.trim();
      elements.btnClearUrl.classList.remove("hidden");
      if (elements.btnPasteClipboard) elements.btnPasteClipboard.classList.add("hidden");
      showToast("Pasted link from clipboard", "info");
      if (text.includes("spotify.com") || text.includes("spotify:")) {
        elements.fetchForm.requestSubmit();
      }
    } else {
      showToast("Clipboard is empty", "info");
    }
  } catch (err) {
    showToast("Please allow clipboard permissions to paste", "info");
  }
}

// Loading State (Spinner + Skeleton Shimmer)
function setLoadingState(isLoading) {
  if (isLoading) {
    elements.btnFetch.disabled = true;
    elements.fetchSpinner.classList.remove("hidden");
    elements.btnFetch.querySelector(".btn-text").textContent = "Loading...";
    if (elements.skeletonSection) elements.skeletonSection.classList.remove("hidden");
    if (elements.playlistSection) elements.playlistSection.classList.add("hidden");
  } else {
    elements.btnFetch.disabled = false;
    elements.fetchSpinner.classList.add("hidden");
    elements.btnFetch.querySelector(".btn-text").textContent = "Load Playlist";
    if (elements.skeletonSection) elements.skeletonSection.classList.add("hidden");
  }
}

// Fetch Metadata & Track List from Backend
async function fetchPlaylistData(url) {
  setLoadingState(true);
  try {
    const res = await fetch("/api/playlist/info", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: url }),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Could not retrieve playlist metadata.");
    }

    const data = await res.json();
    state.currentPlaylist = data;
    saveRecentPlaylist(data, url);
    renderPlaylistView(data);
    showToast(`Loaded "${data.title}" (${data.total_tracks} tracks)`, "success");
  } catch (err) {
    showToast("Error loading playlist: " + err.message, "error", 5000);
  } finally {
    setLoadingState(false);
  }
}

// Progressive Chunked Track Rendering Setup
function setupIntersectionObserver() {
  if ("IntersectionObserver" in window) {
    state.observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting && state.currentPlaylist) {
            renderNextTrackBatch();
          }
        });
      },
      { rootMargin: "300px" }
    );
    if (elements.tracksSentinel) {
      state.observer.observe(elements.tracksSentinel);
    }
  }
}

// Render Playlist Header & Initialize Progressive Track Rendering
function renderPlaylistView(data) {
  state.selectedTrackIds.clear();
  state.failedTrackIds.clear();
  state.downloadedFilesMap.clear();

  // Populate Header
  elements.plCover.src = data.cover_url || "https://community.spotify.com/t5/image/serverpage/image-id/25294i2836BD1C1A311FFE/image-size/large?v=v2&px=999";
  elements.plType.textContent = (data.type || "PLAYLIST").toUpperCase();
  elements.plTitle.textContent = data.title;
  elements.plDesc.textContent = data.description || (data.author ? `Curated by ${data.author}` : "");
  elements.plAuthor.textContent = data.author || "Spotify";
  elements.plCount.textContent = data.total_tracks;
  elements.plDuration.textContent = data.total_duration_formatted;

  // Reset filter input
  if (elements.trackFilterInput) {
    elements.trackFilterInput.value = "";
    if (elements.btnClearFilter) elements.btnClearFilter.classList.add("hidden");
    elements.filterCounter.textContent = `Showing all ${data.total_tracks} songs`;
  }

  // Build target download directory preview
  const sanitizedTitle = sanitizeFilename(data.title);
  state.currentOutputDir = `${state.defaultOutputDir}\\${sanitizedTitle}`;

  // Select all tracks by default
  data.tracks.forEach((track) => state.selectedTrackIds.add(track.id));

  // Initialize filtered track list & progressive render
  state.activeFilterChip = "all";
  if (elements.filterQuickChips) {
    elements.filterQuickChips.querySelectorAll(".filter-chip").forEach((c) => c.classList.remove("active"));
    const allChip = elements.filterQuickChips.querySelector('[data-filter="all"]');
    if (allChip) allChip.classList.add("active");
  }

  state.filteredTracks = [...data.tracks];
  state.renderedTrackCount = 0;
  state.lastCheckedIndex = -1;
  elements.tracksList.innerHTML = "";

  renderNextTrackBatch();

  updateSelectionSummary();
  updateFilterChipBadges();
  elements.playlistSection.classList.remove("hidden");
  elements.playlistSection.scrollIntoView({ behavior: "smooth" });
}

// Render Next Batch (50 items) with DocumentFragment for 60 FPS performance
function renderNextTrackBatch() {
  if (!state.currentPlaylist || state.filteredTracks.length === 0) {
    if (elements.tracksSentinel) elements.tracksSentinel.classList.add("hidden");
    return;
  }

  const start = state.renderedTrackCount;
  if (start >= state.filteredTracks.length) {
    if (elements.tracksSentinel) elements.tracksSentinel.classList.add("hidden");
    return;
  }

  const end = Math.min(start + state.batchSize, state.filteredTracks.length);
  const fragment = document.createDocumentFragment();

  for (let i = start; i < end; i++) {
    const track = state.filteredTracks[i];
    const row = document.createElement("div");
    row.className = "track-row";
    row.id = `track-row-${track.id}`;

    const isChecked = state.selectedTrackIds.has(track.id);
    const hasPreview = Boolean(track.preview_url);
    const isDownloaded = state.downloadedFilesMap.has(track.id);

    // Active status fallback
    let statusClass = "queued";
    let statusText = "Ready";
    if (isDownloaded) {
      statusClass = "completed";
      statusText = "Downloaded";
    } else if (state.failedTrackIds.has(track.id)) {
      statusClass = "failed";
      statusText = "Failed";
    } else if (state.activeDownloadsMap.has(track.id)) {
      const activeInfo = state.activeDownloadsMap.get(track.id);
      statusClass = activeInfo.status || "downloading";
      statusText = activeInfo.message || statusClass;
    }

    row.innerHTML = `
      <div class="col-check">
        <input type="checkbox" class="track-checkbox" data-id="${track.id}" data-index="${i}" ${isChecked ? "checked" : ""} />
      </div>
      <div class="col-num">${i + 1}</div>
      <div class="col-title">
        <img src="${track.cover_url || state.currentPlaylist.cover_url}" class="track-thumbnail" alt="" loading="lazy" />
        <div class="track-details">
          <div class="track-name-row">
            <span class="track-name" title="${escapeHtml(track.title)}">${escapeHtml(track.title)}</span>
            ${track.is_explicit ? '<span class="explicit-tag">E</span>' : ""}
            ${
              isDownloaded
                ? `<button type="button" class="btn-preview-play btn-hq-play" data-id="${track.id}" title="Play Full HQ Downloaded Track"><i data-lucide="play-circle"></i></button>`
                : hasPreview
                ? `<button type="button" class="btn-preview-play" data-id="${track.id}" title="Preview 30s"><i data-lucide="play-circle"></i></button>`
                : ""
            }
          </div>
          <span class="track-artist" title="${escapeHtml(track.artists)}">${escapeHtml(track.artists)}</span>
        </div>
      </div>
      <div class="col-album" title="${escapeHtml(track.album || state.currentPlaylist.title)}">${escapeHtml(track.album || state.currentPlaylist.title)}</div>
      <div class="col-dur">${track.duration_formatted}</div>
      <div class="col-actions">
        <button type="button" class="btn-single-dl" data-id="${track.id}" title="Download '${escapeHtml(track.title)}' immediately">
          <i data-lucide="download"></i>
        </button>
      </div>
      <div class="col-status">
        <span class="badge-status ${statusClass}" id="status-badge-${track.id}">${statusText}</span>
      </div>
    `;

    // Row Checkbox listener with Shift-Click range selection
    const chk = row.querySelector(".track-checkbox");
    chk.addEventListener("click", (e) => {
      const clickedIdx = parseInt(chk.getAttribute("data-index"), 10);
      if (e.shiftKey && state.lastCheckedIndex !== -1 && state.lastCheckedIndex !== clickedIdx) {
        const minIdx = Math.min(state.lastCheckedIndex, clickedIdx);
        const maxIdx = Math.max(state.lastCheckedIndex, clickedIdx);
        const targetChecked = chk.checked;

        for (let j = minIdx; j <= maxIdx; j++) {
          const t = state.filteredTracks[j];
          if (!t) continue;
          if (targetChecked) {
            state.selectedTrackIds.add(t.id);
          } else {
            state.selectedTrackIds.delete(t.id);
          }
          const rowChk = document.querySelector(`.track-checkbox[data-index="${j}"]`);
          if (rowChk) rowChk.checked = targetChecked;
        }
      } else {
        if (chk.checked) {
          state.selectedTrackIds.add(track.id);
        } else {
          state.selectedTrackIds.delete(track.id);
        }
      }
      state.lastCheckedIndex = clickedIdx;
      updateSelectionSummary();
      updateFilterChipBadges();
    });

    // 1-Click Single Track Download button
    const btnSingleDl = row.querySelector(".btn-single-dl");
    btnSingleDl.addEventListener("click", () => {
      downloadSingleTrack(track);
    });

    // Audio play button listener (Preview or Full HQ Download)
    const btnPlay = row.querySelector(".btn-preview-play");
    if (btnPlay) {
      btnPlay.addEventListener("click", () => handleTrackPlayClick(track));
    }

    fragment.appendChild(row);
  }

  elements.tracksList.appendChild(fragment);
  state.renderedTrackCount = end;

  // Update Sentinel Button / Visibility
  if (elements.tracksSentinel) {
    if (state.renderedTrackCount < state.filteredTracks.length) {
      elements.tracksSentinel.classList.remove("hidden");
      const remaining = state.filteredTracks.length - state.renderedTrackCount;
      if (elements.btnLoadMore) {
        elements.btnLoadMore.innerHTML = `<i data-lucide="chevrons-down"></i> Load More Tracks (${remaining} remaining)`;
      }
    } else {
      elements.tracksSentinel.classList.add("hidden");
    }
  }

  if (window.lucide) {
    window.lucide.createIcons();
  }
}

// In-Playlist Live Filter (Text Search + Quick Filter Chips)
function filterTracks() {
  const query = elements.trackFilterInput ? elements.trackFilterInput.value.trim().toLowerCase() : "";
  if (elements.btnClearFilter) {
    if (query.length > 0) {
      elements.btnClearFilter.classList.remove("hidden");
    } else {
      elements.btnClearFilter.classList.add("hidden");
    }
  }

  if (!state.currentPlaylist) return;

  state.filteredTracks = state.currentPlaylist.tracks.filter((t) => {
    // 1. Text Search Match
    if (query.length > 0) {
      const text = `${t.title} ${t.artists} ${t.album || ""}`.toLowerCase();
      if (!text.includes(query)) return false;
    }

    // 2. Quick Filter Chip Match
    if (state.activeFilterChip === "selected") {
      return state.selectedTrackIds.has(t.id);
    }
    if (state.activeFilterChip === "unselected") {
      return !state.selectedTrackIds.has(t.id);
    }
    if (state.activeFilterChip === "downloaded") {
      return state.downloadedFilesMap.has(t.id);
    }
    if (state.activeFilterChip === "failed") {
      return state.failedTrackIds.has(t.id);
    }

    return true;
  });

  // Reset rendering pointer and re-render from batch 0
  state.renderedTrackCount = 0;
  state.lastCheckedIndex = -1;
  elements.tracksList.innerHTML = "";

  if (state.filteredTracks.length === 0) {
    elements.tracksList.innerHTML = `
      <div class="tracks-empty-state">
        <i data-lucide="search-x"></i>
        <h3>No matching songs found</h3>
        <p>No tracks match "${escapeHtml(query)}" under the current filter.</p>
      </div>
    `;
    if (elements.tracksSentinel) elements.tracksSentinel.classList.add("hidden");
    if (window.lucide) window.lucide.createIcons();
  } else {
    renderNextTrackBatch();
  }

  const total = state.currentPlaylist.tracks.length;
  if (elements.filterCounter) {
    if (query.length === 0 && state.activeFilterChip === "all") {
      elements.filterCounter.textContent = `Showing all ${total} songs`;
    } else {
      elements.filterCounter.textContent = `Showing ${state.filteredTracks.length} of ${total} songs`;
    }
  }
}

// Selection Helpers
function setAllTracksSelection(isSelected) {
  if (!state.currentPlaylist) return;

  const targetTracks = (state.filteredTracks && state.filteredTracks.length < state.currentPlaylist.tracks.length)
    ? state.filteredTracks
    : state.currentPlaylist.tracks;

  targetTracks.forEach((t) => {
    if (isSelected) {
      state.selectedTrackIds.add(t.id);
    } else {
      state.selectedTrackIds.delete(t.id);
    }
  });

  document.querySelectorAll(".track-checkbox").forEach((chk) => {
    const id = chk.getAttribute("data-id");
    chk.checked = state.selectedTrackIds.has(id);
  });

  elements.checkAll.checked = isSelected && state.selectedTrackIds.size === state.currentPlaylist.tracks.length;
  updateSelectionSummary();
  updateFilterChipBadges();
}

function invertTracksSelection() {
  if (!state.currentPlaylist) return;

  const targetTracks = (state.filteredTracks && state.filteredTracks.length < state.currentPlaylist.tracks.length)
    ? state.filteredTracks
    : state.currentPlaylist.tracks;

  targetTracks.forEach((t) => {
    if (state.selectedTrackIds.has(t.id)) {
      state.selectedTrackIds.delete(t.id);
    } else {
      state.selectedTrackIds.add(t.id);
    }
  });

  document.querySelectorAll(".track-checkbox").forEach((chk) => {
    const id = chk.getAttribute("data-id");
    chk.checked = state.selectedTrackIds.has(id);
  });

  updateSelectionSummary();
  updateFilterChipBadges();
  showToast(`Inverted selection: ${state.selectedTrackIds.size} tracks`, "info", 1800);
}

function updateSelectionSummary() {
  const count = state.selectedTrackIds.size;
  const total = state.currentPlaylist ? state.currentPlaylist.tracks.length : 0;
  elements.downloadBtnLabel.textContent = `Download Selected (${count} ${count === 1 ? "track" : "tracks"})`;
  elements.btnStartDownload.disabled = count === 0;
  elements.checkAll.checked = count === total && total > 0;

  if (elements.selectionSummaryPill) {
    elements.selectionSummaryPill.textContent = `${count} of ${total} selected`;
  }
}

// Unified Track Audio Playback Trigger (prevents duplicate listeners)
function handleTrackPlayClick(track) {
  if (state.downloadedFilesMap.has(track.id)) {
    playTrackAudio(track, true, state.downloadedFilesMap.get(track.id));
  } else if (track.preview_url) {
    playTrackAudio(track, false, track.preview_url);
  }
}

// Floating Mini-Player Controls
function setupAudioPlayer() {
  if (!elements.previewPlayer) return;

  elements.previewPlayer.addEventListener("timeupdate", () => {
    const current = elements.previewPlayer.currentTime || 0;
    const total = elements.previewPlayer.duration || state.previewDuration;
    const pct = total > 0 ? (current / total) * 100 : 0;
    if (elements.mpProgressFill) elements.mpProgressFill.style.width = `${pct}%`;
    if (elements.mpCurrentTime) elements.mpCurrentTime.textContent = formatSec(current);
    if (elements.mpTotalTime) elements.mpTotalTime.textContent = formatSec(total);
  });

  elements.previewPlayer.addEventListener("ended", () => {
    if (elements.mpBtnPlay) elements.mpBtnPlay.innerHTML = '<i data-lucide="play"></i>';
    if (elements.equalizerBars) elements.equalizerBars.style.opacity = "0.3";
    resetRowPlayIcons();
    if (window.lucide) window.lucide.createIcons();
  });

  if (elements.mpBtnPlay) {
    elements.mpBtnPlay.addEventListener("click", () => {
      if (elements.previewPlayer.paused) {
        elements.previewPlayer.play();
        elements.mpBtnPlay.innerHTML = '<i data-lucide="pause"></i>';
        if (elements.equalizerBars) elements.equalizerBars.style.opacity = "1";
      } else {
        elements.previewPlayer.pause();
        elements.mpBtnPlay.innerHTML = '<i data-lucide="play"></i>';
        if (elements.equalizerBars) elements.equalizerBars.style.opacity = "0.3";
      }
      if (window.lucide) window.lucide.createIcons();
    });
  }

  if (elements.mpProgressBar) {
    elements.mpProgressBar.addEventListener("click", (e) => {
      const rect = elements.mpProgressBar.getBoundingClientRect();
      const clickX = e.clientX - rect.left;
      const pct = clickX / rect.width;
      const total = elements.previewPlayer.duration || state.previewDuration;
      elements.previewPlayer.currentTime = pct * total;
    });
  }

  if (elements.mpVolume) {
    elements.mpVolume.addEventListener("input", (e) => {
      elements.previewPlayer.volume = parseFloat(e.target.value);
    });
  }

  if (elements.mpBtnMute) {
    elements.mpBtnMute.addEventListener("click", () => {
      elements.previewPlayer.muted = !elements.previewPlayer.muted;
      elements.mpBtnMute.innerHTML = elements.previewPlayer.muted ? '<i data-lucide="volume-x"></i>' : '<i data-lucide="volume-2"></i>';
      if (window.lucide) window.lucide.createIcons();
    });
  }

  if (elements.mpBtnClose) {
    elements.mpBtnClose.addEventListener("click", () => {
      elements.previewPlayer.pause();
      elements.miniPlayer.classList.add("hidden");
      resetRowPlayIcons();
    });
  }
}

function playTrackAudio(track, isHQ, audioUrlOrPath) {
  if (state.currentlyPlayingId === track.id && !elements.previewPlayer.paused) {
    elements.previewPlayer.pause();
    if (elements.mpBtnPlay) elements.mpBtnPlay.innerHTML = '<i data-lucide="play"></i>';
    if (elements.equalizerBars) elements.equalizerBars.style.opacity = "0.3";
    resetRowPlayIcons();
  } else {
    state.currentlyPlayingId = track.id;
    state.isPlayingHQ = isHQ;

    if (isHQ) {
      elements.previewPlayer.src = `/api/audio/stream?path=${encodeURIComponent(audioUrlOrPath)}`;
      state.previewDuration = track.duration_ms ? track.duration_ms / 1000 : 200;
      if (elements.mpQualityBadge) {
        elements.mpQualityBadge.textContent = "HQ Local Track";
        elements.mpQualityBadge.className = "badge-status ready hq";
      }
    } else {
      elements.previewPlayer.src = audioUrlOrPath;
      state.previewDuration = 30;
      if (elements.mpQualityBadge) {
        elements.mpQualityBadge.textContent = "Preview (30s)";
        elements.mpQualityBadge.className = "badge-status queued";
      }
    }

    elements.previewPlayer.play().catch(() => {});

    // Update Mini Player UI
    if (elements.mpCover) elements.mpCover.src = track.cover_url || (state.currentPlaylist ? state.currentPlaylist.cover_url : "");
    if (elements.mpTitle) elements.mpTitle.textContent = track.title;
    if (elements.mpArtist) elements.mpArtist.textContent = track.artists;
    if (elements.mpBtnPlay) elements.mpBtnPlay.innerHTML = '<i data-lucide="pause"></i>';
    if (elements.equalizerBars) elements.equalizerBars.style.opacity = "1";
    if (elements.miniPlayer) elements.miniPlayer.classList.remove("hidden");

    resetRowPlayIcons();
    const rowBtn = document.querySelector(`.btn-preview-play[data-id="${track.id}"]`);
    if (rowBtn) {
      rowBtn.innerHTML = '<i data-lucide="pause-circle"></i>';
      rowBtn.style.color = "var(--spotify-green)";
    }
  }
  if (window.lucide) window.lucide.createIcons();
}

function resetRowPlayIcons() {
  state.currentlyPlayingId = null;
  document.querySelectorAll(".btn-preview-play").forEach((btn) => {
    btn.innerHTML = '<i data-lucide="play-circle"></i>';
    btn.style.color = "";
  });
  if (window.lucide) window.lucide.createIcons();
}

function formatSec(seconds) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s < 10 ? "0" : ""}${s}`;
}

// 1-Click Single-Track Download
async function downloadSingleTrack(track) {
  if (!state.currentPlaylist) return;

  const options = getDownloadOptions();
  updateTrackBadge(track.id, "queued", "Queued");

  // Show Bottom Bar
  elements.downloadBar.classList.remove("hidden");
  elements.barStatusText.textContent = `Downloading "${track.title}"...`;
  elements.barProgressText.textContent = `0 / 1 (0%)`;
  elements.barProgressFill.style.width = "0%";
  state.isDownloading = true;

  showToast(`Downloading "${track.title}" by ${track.artists}`, "info");
  initEventStream();

  try {
    const res = await fetch("/api/download/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        playlist_title: state.currentPlaylist.title,
        tracks: [track],
        options: options,
      }),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Failed to start single track download");
    }
  } catch (err) {
    showToast("Error downloading track: " + err.message, "error");
    state.isDownloading = false;
  }
}

// 1-Click Retry Failed Tracks
async function retryFailedTracks() {
  if (!state.currentPlaylist || state.failedTrackIds.size === 0) return;

  const failedTracks = state.currentPlaylist.tracks.filter((t) => state.failedTrackIds.has(t.id));
  if (failedTracks.length === 0) return;

  const options = getDownloadOptions();
  failedTracks.forEach((t) => {
    updateTrackBadge(t.id, "queued", "Retrying...");
  });

  // Clear from failed set as they are queued
  failedTracks.forEach((t) => state.failedTrackIds.delete(t.id));
  updateFilterChipBadges();

  elements.downloadBar.classList.remove("hidden");
  elements.barStatusText.textContent = `Retrying ${failedTracks.length} failed tracks...`;
  elements.barProgressText.textContent = `0 / ${failedTracks.length} (0%)`;
  elements.barProgressFill.style.width = "0%";
  state.isDownloading = true;

  showToast(`Retrying ${failedTracks.length} failed tracks...`, "info");
  initEventStream();

  try {
    const res = await fetch("/api/download/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        playlist_title: state.currentPlaylist.title,
        tracks: failedTracks,
        options: options,
      }),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Failed to start retry");
    }
  } catch (err) {
    showToast("Error retrying downloads: " + err.message, "error");
    state.isDownloading = false;
  }
}

// Helper to assemble options object
function getDownloadOptions() {
  return {
    output_dir: elements.settingOutdir.value.trim() ? `${elements.settingOutdir.value.trim()}\\${sanitizeFilename(state.currentPlaylist.title)}` : "",
    audio_format: elements.settingFormat.value,
    bitrate: elements.settingBitrate.value,
    filename_format: elements.settingNaming.value,
    create_m3u8: elements.toggleM3u8.checked,
    overwrite: elements.toggleOverwrite.checked,
    embed_artwork: elements.toggleArtwork ? elements.toggleArtwork.checked : true,
    concurrency: parseInt(elements.settingConcurrency ? elements.settingConcurrency.value : "3", 10),
  };
}

// Start Batch Download Process
async function startDownloadProcess() {
  if (!state.currentPlaylist || state.selectedTrackIds.size === 0) return;

  const selectedTracks = state.currentPlaylist.tracks.filter((t) => state.selectedTrackIds.has(t.id));
  const options = getDownloadOptions();
  state.currentOutputDir = options.output_dir;

  // Reset status badges for selected tracks
  selectedTracks.forEach((t) => {
    updateTrackBadge(t.id, "queued", "Queued");
  });

  // Show Bottom Bar
  elements.downloadBar.classList.remove("hidden");
  elements.barStatusText.textContent = "Starting high-speed download...";
  elements.barProgressText.textContent = `0 / ${selectedTracks.length} (0%)`;
  elements.barProgressFill.style.width = "0%";
  if (elements.barSpeedVal) elements.barSpeedVal.textContent = "0 KB/s";
  if (elements.barEtaVal) elements.barEtaVal.textContent = "Calculating...";
  if (elements.barStreamsVal) elements.barStreamsVal.textContent = `${options.concurrency} streams active`;
  elements.btnStartDownload.disabled = true;
  state.isDownloading = true;

  showToast(`Starting download of ${selectedTracks.length} songs at ${options.concurrency}x concurrency!`, "info");

  // Connect to SSE Stream
  initEventStream();

  try {
    const res = await fetch("/api/download/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        playlist_title: state.currentPlaylist.title,
        tracks: selectedTracks,
        options: options,
      }),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Failed to start download");
    }
  } catch (err) {
    showToast("Error starting download: " + err.message, "error");
    elements.downloadBar.classList.add("hidden");
    elements.btnStartDownload.disabled = false;
    state.isDownloading = false;
  }
}

// SSE Event Stream Listener
function initEventStream() {
  if (state.eventSource) {
    state.eventSource.close();
  }

  state.eventSource = new EventSource("/api/download/stream");

  state.eventSource.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data);
      handleServerEvent(payload.type, payload.data);
    } catch (e) {
      // Keep alive / ping
    }
  };

  state.eventSource.onerror = (e) => {
    console.warn("EventSource paused or disconnected.");
  };
}

function handleServerEvent(type, data) {
  if (type === "track_update") {
    const { track_id, status, progress, message, filepath } = data;
    updateTrackBadge(track_id, status, message);

    if (status === "completed") {
      if (filepath) {
        state.downloadedFilesMap.set(track_id, filepath);
      }
      state.failedTrackIds.delete(track_id);
      // Upgrade preview button in row to HQ play button
      const row = document.getElementById(`track-row-${track_id}`);
      if (row) {
        let playBtn = row.querySelector(".btn-preview-play");
        const trackObj = state.currentPlaylist ? state.currentPlaylist.tracks.find((t) => t.id === track_id) : null;
        if (!playBtn && trackObj) {
          const nameRow = row.querySelector(".track-name-row");
          if (nameRow) {
            playBtn = document.createElement("button");
            playBtn.type = "button";
            playBtn.className = "btn-preview-play btn-hq-play";
            playBtn.setAttribute("data-id", track_id);
            playBtn.title = "Play Full HQ Downloaded Track";
            playBtn.innerHTML = '<i data-lucide="play-circle"></i>';
            playBtn.addEventListener("click", () => handleTrackPlayClick(trackObj));
            nameRow.appendChild(playBtn);
            if (window.lucide) window.lucide.createIcons();
          }
        } else if (playBtn && trackObj) {
          playBtn.className = "btn-preview-play btn-hq-play";
          playBtn.title = "Play Full HQ Downloaded Track";
        }
      }
    } else if (status === "failed") {
      state.failedTrackIds.add(track_id);
    }

    updateFilterChipBadges();

    // Track active downloads for the Live Queue Drawer
    if (status === "downloading" || status === "searching" || status === "tagging") {
      let trackInfo = state.currentPlaylist ? state.currentPlaylist.tracks.find((t) => t.id === track_id) : null;
      state.activeDownloadsMap.set(track_id, {
        track_id,
        title: trackInfo ? trackInfo.title : "Track",
        artists: trackInfo ? trackInfo.artists : "Artist",
        cover_url: trackInfo ? trackInfo.cover_url : (state.currentPlaylist ? state.currentPlaylist.cover_url : ""),
        status,
        message,
      });
    } else if (status === "completed" || status === "failed") {
      setTimeout(() => {
        state.activeDownloadsMap.delete(track_id);
        updateQueueDrawer();
      }, 1500);
    }
    updateQueueDrawer();

  } else if (type === "job_progress") {
    const { completed, total, percent, speed, eta, active_count } = data;
    elements.barStatusText.textContent = `Downloading (${completed} of ${total} finished)`;
    elements.barProgressText.textContent = `${completed} / ${total} (${percent}%)`;
    elements.barProgressFill.style.width = `${percent}%`;

    if (elements.barSpeedVal && speed) elements.barSpeedVal.textContent = speed;
    if (elements.barEtaVal && eta) elements.barEtaVal.textContent = eta;
    if (elements.barStreamsVal && active_count !== undefined) {
      elements.barStreamsVal.textContent = `${active_count} active`;
    }
  } else if (type === "job_finished") {
    elements.barStatusText.textContent = `Download complete! ${data.completed} tracks saved.`;
    elements.barProgressText.textContent = `${data.completed} / ${data.total} (100%)`;
    elements.barProgressFill.style.width = "100%";
    if (elements.barEtaVal) elements.barEtaVal.textContent = "Done";
    elements.btnStartDownload.disabled = false;
    state.isDownloading = false;
    state.activeDownloadsMap.clear();
    updateQueueDrawer();
    updateFilterChipBadges();

    if (state.eventSource) state.eventSource.close();

    // Celebration modal popup
    if (elements.completionModal) {
      elements.modalStatCount.textContent = data.completed;
      elements.modalStatTime.textContent = `${data.elapsed_seconds || 0}s`;
      elements.modalStatFailures.textContent = data.failed || 0;
      elements.modalSummaryText.textContent = `Successfully cloned ${data.completed} tracks with authentic ID3 tags and high-res cover art!`;

      if (data.failed && data.failed > 0 && elements.btnModalRetryFailed) {
        elements.btnModalRetryFailed.classList.remove("hidden");
        if (elements.modalFailedCount) elements.modalFailedCount.textContent = data.failed;
      } else if (elements.btnModalRetryFailed) {
        elements.btnModalRetryFailed.classList.add("hidden");
      }

      elements.completionModal.classList.remove("hidden");
    }
    showToast(`🎉 Download complete! ${data.completed} tracks saved.`, "success", 6000);

  } else if (type === "job_cancelled") {
    elements.barStatusText.textContent = "Download cancelled.";
    elements.btnStartDownload.disabled = false;
    state.isDownloading = false;
    state.activeDownloadsMap.clear();
    updateQueueDrawer();

    if (state.eventSource) state.eventSource.close();
    showToast("Download cancelled by user", "info");
  }
}

// Update Expandable Live Queue Drawer UI
function updateQueueDrawer() {
  if (!elements.queueDrawer || !elements.queueItemsContainer) return;
  const count = state.activeDownloadsMap.size;

  if (elements.queueActiveCount) elements.queueActiveCount.textContent = `${count} active`;
  if (elements.btnQueueCount) elements.btnQueueCount.textContent = count;

  if (count === 0) {
    elements.queueItemsContainer.innerHTML = `<div class="queue-empty">No active downloads in flight</div>`;
    return;
  }

  let html = "";
  state.activeDownloadsMap.forEach((item) => {
    html += `
      <div class="queue-item-row">
        <div class="queue-item-left">
          <img src="${escapeHtml(item.cover_url || '')}" class="queue-item-thumb" alt="" />
          <div class="queue-item-info">
            <span class="queue-item-title">${escapeHtml(item.title)}</span>
            <span class="queue-item-sub">${escapeHtml(item.artists)}</span>
          </div>
        </div>
        <span class="badge-status ${item.status}">${escapeHtml(item.message || item.status)}</span>
      </div>
    `;
  });

  elements.queueItemsContainer.innerHTML = html;
}

function updateTrackBadge(trackId, status, message) {
  const badge = document.getElementById(`status-badge-${trackId}`);
  if (!badge) return;

  badge.className = `badge-status ${status}`;
  badge.textContent = message || status;
}

// Cancel Download
async function cancelDownloadProcess() {
  try {
    await fetch("/api/download/cancel", { method: "POST" });
  } catch (err) {
    console.error("Failed to cancel:", err);
  }
}

// Open Folder in Windows Explorer
async function openCurrentDirectory() {
  const targetPath = state.currentOutputDir || state.defaultOutputDir;
  try {
    const res = await fetch("/api/open-folder", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: targetPath }),
    });
    if (res.ok) {
      showToast("Opened music folder in Explorer", "info", 2000);
    }
  } catch (err) {
    alert("Could not open folder in Explorer: " + err.message);
  }
}

// Utility Helpers
function escapeHtml(text) {
  if (!text) return "";
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function sanitizeFilename(name) {
  return name.replace(/[<>:"/\\|?*]/g, "_").trim();
}
