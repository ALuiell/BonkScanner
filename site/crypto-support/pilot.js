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
  document.execCommand('copy');
  helper.remove();
}

function showToast(asset) {
  toast.lastChild.textContent = ` ${asset} address copied.`;
  toast.classList.add('show');
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => toast.classList.remove('show'), 1900);
}

function getCardAddress(element) {
  return element.closest('.fuel-card').querySelector('.address-box code').textContent.trim();
}

document.querySelectorAll('.copy-button').forEach((button) => {
  button.addEventListener('click', async () => {
    await copyText(getCardAddress(button));
    const original = button.textContent;
    button.textContent = 'COPIED!';
    button.classList.add('copied');
    showToast(button.dataset.asset);
    window.setTimeout(() => {
      button.textContent = original;
      button.classList.remove('copied');
    }, 1600);
  });
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
    dialog.dataset.copyLabel = 'COPY ADDRESS';
    dialogCopy.textContent = dialog.dataset.copyLabel;
    dialog.showModal();
  });
});

dialog.querySelector('.modal-close').addEventListener('click', () => dialog.close());
dialog.addEventListener('click', (event) => {
  if (event.target === dialog) dialog.close();
});

dialogCopy.addEventListener('click', async () => {
  await copyText(dialogAddress);
  dialogCopy.textContent = 'COPIED — BONK!';
  showToast(dialogTitle.textContent);
  window.setTimeout(() => {
    dialogCopy.textContent = dialog.dataset.copyLabel || 'COPY ADDRESS';
  }, 1600);
});
