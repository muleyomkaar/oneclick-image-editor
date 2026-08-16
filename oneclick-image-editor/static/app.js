const fileInput = document.getElementById("fileInput");
const browseBtn = document.getElementById("browseBtn");
const replaceBtn = document.getElementById("replaceBtn");
const dropzone = document.getElementById("dropzone");
const editor = document.getElementById("editor");
const previewImage = document.getElementById("previewImage");
const processing = document.getElementById("processing");
const fileName = document.getElementById("fileName");
const imageMeta = document.getElementById("imageMeta");
const undoBtn = document.getElementById("undoBtn");
const resetBtn = document.getElementById("resetBtn");
const compareBtn = document.getElementById("compareBtn");
const downloadBtn = document.getElementById("downloadBtn");
const formatSelect = document.getElementById("formatSelect");
const toast = document.getElementById("toast");
const bgTool = document.getElementById("bgTool");
const bgToolNote = document.getElementById("bgToolNote");
const cropModal = document.getElementById("cropModal");
const cropFrame = document.getElementById("cropFrame");
const cropImage = document.getElementById("cropImage");
const cropApplyBtn = document.getElementById("cropApplyBtn");
const cropCancelBtn = document.getElementById("cropCancelBtn");
const cropCloseBtn = document.getElementById("cropCloseBtn");
const cropZoom = document.getElementById("cropZoom");

let originalBlob = null;
let currentBlob = null;
let currentUrl = null;
let history = [];
let originalUrl = null;
let originalName = "image";
let busy = false;
let cropState = null;

const cropPresets = {
  instagram: { width: 1080, height: 1080, label: "Instagram 1:1" },
  story: { width: 1080, height: 1920, label: "Story 9:16" },
  linkedin: { width: 800, height: 800, label: "LinkedIn 1:1" },
  youtube: { width: 1280, height: 720, label: "YouTube 16:9" },
};

function showToast(message) {
  toast.textContent = message;
  toast.classList.remove("hidden");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.add("hidden"), 3000);
}

function setBusy(value) {
  busy = value;
  processing.classList.toggle("hidden", !value);
  document.querySelectorAll(".tool-card, .preset").forEach(el => {
    if (el !== bgTool || !bgTool.dataset.unavailable) el.disabled = value;
  });
  downloadBtn.disabled = value;
}

function blobUrl(blob) {
  return URL.createObjectURL(blob);
}

function setPreview(blob, metaText = "") {
  if (currentUrl) URL.revokeObjectURL(currentUrl);
  currentUrl = blobUrl(blob);
  previewImage.src = currentUrl;
  imageMeta.textContent = metaText;
  undoBtn.disabled = history.length === 0;
  resetBtn.disabled = !originalBlob;
}

function prettyBytes(bytes) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function fileStem(name) {
  return (name || "image").replace(/\.[^.]+$/, "");
}

function loadFile(file) {
  if (!file || !file.type.startsWith("image/")) {
    showToast("Please choose a PNG, JPG or WEBP image.");
    return;
  }
  originalBlob = file;
  currentBlob = file;
  history = [];
  originalName = fileStem(file.name);
  if (originalUrl) URL.revokeObjectURL(originalUrl);
  originalUrl = blobUrl(file);

  fileName.textContent = file.name;
  setPreview(file, prettyBytes(file.size));
  dropzone.classList.add("hidden");
  editor.classList.remove("hidden");
}

async function applyEdit(action, preset = null, cropPosition = null) {
  if (!currentBlob || busy) return;

  const previous = currentBlob;
  setBusy(true);

  try {
    const form = new FormData();
    form.append("file", currentBlob, `${originalName}.png`);
    form.append("action", action);
    if (preset) form.append("preset", preset);
    if (cropPosition) {
      form.append("crop_x", cropPosition.x.toFixed(4));
      form.append("crop_y", cropPosition.y.toFixed(4));
      form.append("crop_zoom", cropPosition.zoom.toFixed(2));
    }
    form.append("output_format", formatSelect.value);

    // Compression is intentionally more aggressive.
    form.append("quality", action === "compress" ? "72" : "88");

    const response = await fetch("/api/edit", {
      method: "POST",
      body: form,
    });

    if (!response.ok) {
      let message = "Could not edit this image.";
      try {
        const data = await response.json();
        message = data.detail || message;
      } catch (_) {}
      throw new Error(message);
    }

    const result = await response.blob();
    history.push(previous);
    currentBlob = result;

    const width = response.headers.get("X-Image-Width");
    const height = response.headers.get("X-Image-Height");
    const format = response.headers.get("X-Output-Format");
    const details = [
      width && height ? `${width} × ${height}` : "",
      format || "",
      prettyBytes(result.size),
    ].filter(Boolean).join(" · ");

    setPreview(result, details);

    if (action === "compress") {
      const saved = previous.size > 0
        ? Math.max(0, Math.round((1 - result.size / previous.size) * 100))
        : 0;
      showToast(saved > 0 ? `Compressed — about ${saved}% smaller.` : "Compressed and optimised.");
    }
  } catch (error) {
    showToast(error.message || "Something went wrong.");
  } finally {
    setBusy(false);
  }
}

function undo() {
  if (!history.length || busy) return;
  currentBlob = history.pop();
  setPreview(currentBlob, prettyBytes(currentBlob.size));
}

function reset() {
  if (!originalBlob || busy) return;
  currentBlob = originalBlob;
  history = [];
  setPreview(originalBlob, prettyBytes(originalBlob.size));
  showToast("Back to the original.");
}

async function downloadCurrent() {
  if (!currentBlob || busy) return;

  // Re-encode if user changed the desired output format.
  setBusy(true);
  try {
    const form = new FormData();
    form.append("file", currentBlob, `${originalName}.png`);
    form.append("action", "convert");
    form.append("output_format", formatSelect.value);
    form.append("quality", "88");

    const response = await fetch("/api/edit", { method: "POST", body: form });
    if (!response.ok) throw new Error("Could not prepare the download.");

    const result = await response.blob();
    const ext = formatSelect.value === "JPEG" ? "jpg" : formatSelect.value.toLowerCase();
    const url = blobUrl(result);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${originalName}-oneclick.${ext}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  } catch (error) {
    showToast(error.message || "Download failed.");
  } finally {
    setBusy(false);
  }
}

browseBtn.addEventListener("click", () => fileInput.click());
replaceBtn.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", e => loadFile(e.target.files[0]));

["dragenter", "dragover"].forEach(type => {
  dropzone.addEventListener(type, e => {
    e.preventDefault();
    dropzone.classList.add("dragging");
  });
});
["dragleave", "drop"].forEach(type => {
  dropzone.addEventListener(type, e => {
    e.preventDefault();
    dropzone.classList.remove("dragging");
  });
});
dropzone.addEventListener("drop", e => loadFile(e.dataTransfer.files[0]));

document.querySelectorAll(".tool-card").forEach(button => {
  button.addEventListener("click", () => applyEdit(button.dataset.action));
});
function updateCropPreview() {
  if (!cropState || !cropImage.naturalWidth) return;
  const frameWidth = cropFrame.clientWidth;
  const frameHeight = cropFrame.clientHeight;
  const scale = Math.max(frameWidth / cropImage.naturalWidth, frameHeight / cropImage.naturalHeight) * cropState.zoom;
  const width = cropImage.naturalWidth * scale;
  const height = cropImage.naturalHeight * scale;
  cropImage.style.width = `${width}px`;
  cropImage.style.height = `${height}px`;
  cropImage.style.left = `${(frameWidth - width) * cropState.x}px`;
  cropImage.style.top = `${(frameHeight - height) * cropState.y}px`;
}

function openCrop(preset) {
  if (!currentBlob || busy || !cropPresets[preset]) {
    if (!currentBlob) showToast("Choose an image before selecting a size.");
    return;
  }
  const config = cropPresets[preset];
  cropState = { preset, x: 0.5, y: 0.5, zoom: 1, pointerId: null };
  const maxWidth = Math.min(window.innerWidth * 0.82, 628);
  const maxHeight = Math.min(window.innerHeight * 0.52, 480);
  const previewScale = Math.min(maxWidth / config.width, maxHeight / config.height);
  cropFrame.style.width = `${Math.round(config.width * previewScale)}px`;
  cropFrame.style.height = `${Math.round(config.height * previewScale)}px`;
  document.getElementById("cropTitle").textContent = `Position for ${config.label}`;
  cropZoom.value = "1";
  cropImage.src = currentUrl;
  cropImage.onload = updateCropPreview;
  cropModal.classList.remove("hidden");
}

function closeCrop() {
  cropModal.classList.add("hidden");
  cropState = null;
}

cropFrame.addEventListener("pointerdown", event => {
  if (!cropState) return;
  cropState.pointerId = event.pointerId;
  cropState.startClientX = event.clientX;
  cropState.startClientY = event.clientY;
  cropState.startX = cropState.x;
  cropState.startY = cropState.y;
  cropFrame.setPointerCapture(event.pointerId);
  cropFrame.classList.add("dragging");
});
cropFrame.addEventListener("pointermove", event => {
  if (!cropState || cropState.pointerId !== event.pointerId || !cropImage.naturalWidth) return;
  const frameWidth = cropFrame.clientWidth;
  const frameHeight = cropFrame.clientHeight;
  const scale = Math.max(frameWidth / cropImage.naturalWidth, frameHeight / cropImage.naturalHeight) * cropState.zoom;
  const overflowX = Math.max(0, cropImage.naturalWidth * scale - frameWidth);
  const overflowY = Math.max(0, cropImage.naturalHeight * scale - frameHeight);
  if (overflowX) cropState.x = Math.max(0, Math.min(1, cropState.startX - (event.clientX - cropState.startClientX) / overflowX));
  if (overflowY) cropState.y = Math.max(0, Math.min(1, cropState.startY - (event.clientY - cropState.startClientY) / overflowY));
  updateCropPreview();
});
function endCropDrag(event) {
  if (!cropState || cropState.pointerId !== event.pointerId) return;
  cropState.pointerId = null;
  cropFrame.classList.remove("dragging");
}
cropFrame.addEventListener("pointerup", endCropDrag);
cropFrame.addEventListener("pointercancel", endCropDrag);
cropApplyBtn.addEventListener("click", () => {
  if (!cropState) return;
  const selection = { preset: cropState.preset, x: cropState.x, y: cropState.y, zoom: cropState.zoom };
  closeCrop();
  applyEdit("resize", selection.preset, selection);
});
cropCancelBtn.addEventListener("click", closeCrop);
cropCloseBtn.addEventListener("click", closeCrop);
cropZoom.addEventListener("input", () => {
  if (!cropState) return;
  cropState.zoom = Number(cropZoom.value);
  updateCropPreview();
});
cropModal.addEventListener("click", event => { if (event.target === cropModal) closeCrop(); });
document.addEventListener("keydown", event => { if (event.key === "Escape" && cropState) closeCrop(); });

document.querySelectorAll(".preset").forEach(button => {
  button.addEventListener("click", () => openCrop(button.dataset.preset));
});

undoBtn.addEventListener("click", undo);
resetBtn.addEventListener("click", reset);
downloadBtn.addEventListener("click", downloadCurrent);

function compareStart(e) {
  if (!originalUrl || busy) return;
  e.preventDefault();
  previewImage.src = originalUrl;
}
function compareEnd(e) {
  if (!currentUrl) return;
  e?.preventDefault();
  previewImage.src = currentUrl;
}
compareBtn.addEventListener("mousedown", compareStart);
compareBtn.addEventListener("mouseup", compareEnd);
compareBtn.addEventListener("mouseleave", compareEnd);
compareBtn.addEventListener("touchstart", compareStart, { passive: false });
compareBtn.addEventListener("touchend", compareEnd);

async function loadCapabilities() {
  try {
    const response = await fetch("/api/capabilities");
    const caps = await response.json();
    document.getElementById("maxUpload").textContent = caps.maxUploadMB || 12;

    if (caps.backgroundRemoval) {
      bgToolNote.textContent = "AI cutout, transparent PNG";
    } else {
      bgTool.disabled = true;
      bgTool.dataset.unavailable = "true";
      bgToolNote.textContent = "Optional AI add-on";
      bgTool.title = 'Install rembg[cpu] to enable';
    }
  } catch (_) {
    bgTool.disabled = true;
    bgToolNote.textContent = "Optional AI add-on";
  }
}

loadCapabilities();
