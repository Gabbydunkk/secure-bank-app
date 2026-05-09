// src/lib/location.ts
// Derives a lightweight location context from browser locale/timezone without
// requiring geolocation permission or third-party APIs.
//
// Why this exists:
// - Backend fraud scoring expects X-Location-Country / X-Location-City headers.
// - Without these headers, all requests look location-unknown.
//
// Notes:
// - This is heuristic context (locale/timezone based), not GPS-accurate.
// - It is intentionally non-blocking and safe to fail.

export interface LocationContext {
  country: string | null
  city: string | null
}

const DEMO_LOCATION_KEY = 'demo.location.override.v1'
let _cachedLocation: LocationContext | null = null

function readDemoOverride(): LocationContext | null {
  try {
    const raw = window.localStorage.getItem(DEMO_LOCATION_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as LocationContext
    if (!parsed || typeof parsed !== 'object') return null
    return {
      country: parsed.country ?? null,
      city: parsed.city ?? null,
    }
  } catch {
    return null
  }
}

export function setDemoLocationOverride(location: LocationContext | null): void {
  if (location == null) {
    window.localStorage.removeItem(DEMO_LOCATION_KEY)
    return
  }
  window.localStorage.setItem(DEMO_LOCATION_KEY, JSON.stringify(location))
}

export function getDemoLocationOverride(): LocationContext | null {
  return readDemoOverride()
}

function parseCountryFromLocale(locale: string | undefined): string | null {
  if (!locale) return null
  // Most browsers provide BCP-47 tags like "en-GB" or "en-US".
  const normalized = locale.replace('_', '-')
  const parts = normalized.split('-')
  if (parts.length < 2) return null
  const region = parts[parts.length - 1]
  return /^[A-Za-z]{2}$/.test(region) ? region.toUpperCase() : null
}

function parseCityFromTimeZone(timeZone: string | undefined): string | null {
  if (!timeZone) return null
  // Examples:
  //   "Europe/London"              -> "London"
  //   "America/Argentina/Buenos_Aires" -> "Buenos Aires"
  const segments = timeZone.split('/')
  if (segments.length < 2) return null
  const raw = segments[segments.length - 1]
  const cleaned = raw.replace(/_/g, ' ').trim()
  return cleaned || null
}

export async function getLocationContext(): Promise<LocationContext> {
  const demoOverride = readDemoOverride()
  if (demoOverride) return demoOverride

  if (_cachedLocation) return _cachedLocation

  const locale =
    (Array.isArray(navigator.languages) && navigator.languages[0]) ||
    navigator.language ||
    undefined
  const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone

  _cachedLocation = {
    country: parseCountryFromLocale(locale),
    city: parseCityFromTimeZone(timeZone),
  }
  return _cachedLocation
}

