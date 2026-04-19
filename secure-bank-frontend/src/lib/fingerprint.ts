// src/lib/fingerprint.ts
// Generates a stable device fingerprint and caches it for the session.
//
// Why this matters:
//   The backend's DeviceAnomalyRule adds +35 to the fraud score for every
//   request that comes from an unrecognised device fingerprint. Without this
//   header, every user looks like a new unknown device on every request,
//   causing legitimate transactions to be flagged constantly.
//
// This implementation uses browser signals available without any library.
// For higher accuracy in production, replace with FingerprintJS Pro:
//   https://fingerprint.com (paid, but significantly more stable)
//
// The fingerprint is stable for the lifetime of the browser installation
// unless the user clears site data or changes hardware.

let _cachedFingerprint: string | null = null

async function buildFingerprint(): Promise<string> {
  const components: (string | number)[] = [
    navigator.userAgent,
    navigator.language,
    navigator.languages.join(','),
    `${screen.width}x${screen.height}x${screen.colorDepth}`,
    new Date().getTimezoneOffset(),
    navigator.hardwareConcurrency ?? 0,
    navigator.maxTouchPoints ?? 0,
    navigator.platform,
    // WebGL renderer string — GPU-specific, very stable
    getWebGLRenderer(),
    // Canvas fingerprint — font rendering is OS and GPU specific
    await getCanvasFingerprint(),
  ]

  const raw = components.join('||')
  return hashString(raw)
}

function getWebGLRenderer(): string {
  try {
    const canvas = document.createElement('canvas')
    const gl =
      canvas.getContext('webgl') ?? canvas.getContext('experimental-webgl')
    if (!gl) return 'no-webgl'
    const ext = (gl as WebGLRenderingContext).getExtension('WEBGL_debug_renderer_info')
    if (!ext) return 'no-ext'
    return (gl as WebGLRenderingContext).getParameter(ext.UNMASKED_RENDERER_WEBGL) ?? 'unknown'
  } catch {
    return 'webgl-error'
  }
}

async function getCanvasFingerprint(): Promise<string> {
  try {
    const canvas = document.createElement('canvas')
    canvas.width = 200
    canvas.height = 40
    const ctx = canvas.getContext('2d')
    if (!ctx) return 'no-canvas'

    ctx.textBaseline = 'top'
    ctx.font = '14px Arial'
    ctx.fillStyle = '#f60'
    ctx.fillRect(0, 0, 200, 40)
    ctx.fillStyle = '#069'
    ctx.fillText('SecureBank 🔐', 2, 2)
    ctx.fillStyle = 'rgba(102, 204, 0, 0.7)'
    ctx.fillText('SecureBank 🔐', 4, 4)

    return canvas.toDataURL()
  } catch {
    return 'canvas-error'
  }
}

async function hashString(input: string): Promise<string> {
  const encoder = new TextEncoder()
  const data = encoder.encode(input)
  const hashBuffer = await crypto.subtle.digest('SHA-256', data)
  const hashArray = Array.from(new Uint8Array(hashBuffer))
  return hashArray.map(b => b.toString(16).padStart(2, '0')).join('')
}

/**
 * Returns a stable SHA-256 hash of browser signals.
 * Result is cached in memory — the async work runs only once per session.
 */
export async function getDeviceFingerprint(): Promise<string> {
  if (_cachedFingerprint !== null) return _cachedFingerprint
  _cachedFingerprint = await buildFingerprint()
  return _cachedFingerprint
}