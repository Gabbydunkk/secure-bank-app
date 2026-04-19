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

let _cachedLocation: LocationContext | null = null

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

