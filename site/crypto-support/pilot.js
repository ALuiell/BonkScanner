const toast = document.querySelector('.toast');
const dialog = document.querySelector('.qr-dialog');
const dialogTitle = dialog.querySelector('#qr-title');
const dialogNetwork = dialog.querySelector('.modal-network');
const dialogKicker = dialog.querySelector('.modal-kicker');
const dialogQrImage = dialog.querySelector('.live-qr');
const dialogNote = dialog.querySelector('.modal-note');
const dialogCopy = dialog.querySelector('.modal-copy');
let toastTimer;
let dialogAddress = '';
let dialogCopyGeneration = 0;
const copyFeedbackTimers = new WeakMap();

function syncAnimationVisibility() {
  document.documentElement.classList.toggle('animations-paused', document.hidden);
}

document.addEventListener('visibilitychange', syncAnimationVisibility);
syncAnimationVisibility();

const radar = document.querySelector('.radar');
const pendingMarkers = new Set();
let markerFrame = 0;

function scheduleMarkerReveal() {
  if (!markerFrame && pendingMarkers.size && !document.hidden && !radar.classList.contains('radar-paused')) {
    markerFrame = requestAnimationFrame(revealReadyMarkers);
  }
}

function revealReadyMarkers() {
  markerFrame = 0;
  const style = getComputedStyle(radar);
  const moving = style.animationName.includes('radar-spin');
  const beamAngle = parseFloat(style.getPropertyValue('--radar-angle'));
  const firstScan = parseFloat(style.getPropertyValue('--radar-revealed')) < 360;
  const bounds = radar.getBoundingClientRect();

  pendingMarkers.forEach((marker) => {
    const box = marker.getBoundingClientRect();
    const x = box.left + box.width / 2 - (bounds.left + bounds.width / 2);
    const y = box.top + box.height / 2 - (bounds.top + bounds.height / 2);
    const angle = (Math.atan2(x, -y) * 180 / Math.PI + 360) % 360;
    // Include the surrounding glow when checking whether the whole marker is
    // inside the transparent sector ahead of the beam (0..172.8 degrees).
    const radius = Math.hypot(box.width / 2 + 16, box.height / 2 + 16);
    const halfAngle = Math.asin(Math.min(1, radius / Math.hypot(x, y))) * 180 / Math.PI;
    const ahead = (angle - beamAngle + 360) % 360;
    const unscanned = firstScan && beamAngle < angle - halfAngle;
    if (!moving || unscanned || (ahead > halfAngle && ahead < 172.8 - halfAngle)) {
      marker.classList.add('marker-ready');
      pendingMarkers.delete(marker);
    }
  });
  // Only runs while decoded images are waiting for an invisible part of the
  // sweep. Once armed, their pixel-by-pixel reveal and fade stay entirely CSS.
  scheduleMarkerReveal();
}

radar.querySelectorAll('.radar-marker').forEach((marker) => {
  marker.querySelector('img').decode().then(() => {
    pendingMarkers.add(marker);
    scheduleMarkerReveal();
  }).catch(() => {
    // A failed image stays hidden; the beam and the other detections continue.
  });
});
document.addEventListener('visibilitychange', scheduleMarkerReveal);
window.matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change', scheduleMarkerReveal);

if ('IntersectionObserver' in window) {
  const radarObserver = new IntersectionObserver(([entry]) => {
    radar.classList.toggle('radar-paused', !entry.isIntersecting);
    scheduleMarkerReveal();
  });
  radarObserver.observe(radar);
} else {
  const syncRadarVisibility = () => {
    const bounds = radar.getBoundingClientRect();
    const viewportHeight = document.documentElement.clientHeight;
    radar.classList.toggle('radar-paused', bounds.bottom <= 0 || bounds.top >= viewportHeight);
    scheduleMarkerReveal();
  };

  window.addEventListener('scroll', syncRadarVisibility, { passive: true });
  window.addEventListener('resize', syncRadarVisibility);
  syncRadarVisibility();
}

async function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const helper = document.createElement('textarea');
  helper.value = text;
  helper.setAttribute('readonly', '');
  helper.style.position = 'fixed';
  helper.style.opacity = '0';
  document.body.appendChild(helper);
  helper.select();
  try {
    if (!document.execCommand('copy')) throw new Error('Clipboard unavailable');
  } finally {
    helper.remove();
  }
}

function showToast(message, isError = false) {
  toast.querySelector('.toast-message').textContent = message;
  toast.querySelector('strong').textContent = isError ? '!' : '✓';
  toast.classList.toggle('error', isError);
  toast.classList.add('show');
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => toast.classList.remove('show'), isError ? 4500 : 1900);
}

function getCardAddress(element) {
  return element.closest('.fuel-card').querySelector('.address-box code').textContent.trim();
}

function resetCopyFeedback(button, addressBox = null) {
  window.clearTimeout(copyFeedbackTimers.get(button));
  button.classList.remove('copied');
  button.setAttribute('aria-label', button.dataset.copyLabel || 'Copy address');
  addressBox?.classList.remove('copy-confirmed');
}

async function copyWithFeedback(button, address, asset, addressBox = null) {
  if (button.disabled) return;
  const generation = dialogCopyGeneration;
  resetCopyFeedback(button, addressBox);
  button.disabled = true;
  try {
    await copyText(address);
    if (button === dialogCopy && (generation !== dialogCopyGeneration || !dialog.open)) return;
    button.classList.add('copied');
    button.setAttribute('aria-label', `${asset} address copied`);
    if (addressBox) {
      // Restart the brief pulse even when the user copies twice in succession.
      void addressBox.offsetWidth;
      addressBox.classList.add('copy-confirmed');
    }
    showToast(`${asset} address copied.`);
    copyFeedbackTimers.set(button, window.setTimeout(() => resetCopyFeedback(button, addressBox), 1600));
  } catch {
    showToast('Could not copy. Please select and copy the address manually.', true);
  } finally {
    button.disabled = false;
  }
}

document.querySelectorAll('.copy-button').forEach((button) => {
  button.dataset.copyLabel = `Copy ${button.dataset.asset} address`;
  resetCopyFeedback(button);
  button.addEventListener('click', () => copyWithFeedback(
    button, getCardAddress(button), button.dataset.asset,
    button.closest('.fuel-card').querySelector('.address-box'),
  ));
});

document.querySelectorAll('[data-qr]').forEach((button) => {
  button.addEventListener('click', () => {
    dialogTitle.textContent = button.dataset.asset;
    dialogNetwork.textContent = button.dataset.network;
    dialogAddress = getCardAddress(button);
    dialogKicker.textContent = 'WALLET QR';
    dialogNote.textContent = 'Scan with a wallet that supports the exact network shown above.';
    dialogQrImage.src = button.dataset.qrImage;
    dialogQrImage.alt = `${button.dataset.asset} receiving address QR code`;
    dialogCopyGeneration += 1;
    dialogCopy.dataset.copyLabel = `Copy ${button.dataset.asset} address`;
    resetCopyFeedback(dialogCopy);
    dialog.showModal();
  });
});

dialog.querySelector('.modal-close').addEventListener('click', () => dialog.close());
dialog.addEventListener('close', () => {
  dialogCopyGeneration += 1;
  resetCopyFeedback(dialogCopy);
});
dialog.addEventListener('click', (event) => {
  if (event.target === dialog) dialog.close();
});

dialogCopy.addEventListener('click', () => copyWithFeedback(dialogCopy, dialogAddress, dialogTitle.textContent));
