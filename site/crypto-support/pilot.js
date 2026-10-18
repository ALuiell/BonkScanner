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
if ('IntersectionObserver' in window) {
  const radarObserver = new IntersectionObserver(([entry]) => {
    radar.classList.toggle('radar-paused', !entry.isIntersecting);
  });
  radarObserver.observe(radar);
} else {
  const syncRadarVisibility = () => {
    const bounds = radar.getBoundingClientRect();
    const viewportHeight = document.documentElement.clientHeight;
    radar.classList.toggle('radar-paused', bounds.bottom <= 0 || bounds.top >= viewportHeight);
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
