/**
 * geo.js — location + growing-degree-day (GDD) phenology.
 *
 * The science: a plant reaches a phenological stage (leaf-out, flower, fruit)
 * at roughly a fixed amount of accumulated heat — growing-degree-days,
 *   GDD = Σ max(0, (Tmax + Tmin)/2 − Tbase).
 * A warmer site (lower latitude / lower elevation) accumulates that heat
 * earlier in the year, so its foraging season shifts earlier. We estimate the
 * day-shift between the user's location and the region baseline from real
 * daily temperature (Open-Meteo archive, no API key) and use it to localize
 * the season strip and the "in season now" verdict.
 *
 * First-order assumption (stated honestly in the UI): the shift is treated as
 * roughly constant across the season. Tbase is a generic 10 °C / 50 °F — fine
 * for a relative comparison between two nearby sites, not a per-species model.
 */

const GDD_BASE_C = 10;
const EARTH_RADIUS_KM = 6371;

/** Haversine distance in km between two [lat, lng] points. */
function haversineKm(lat1, lon1, lat2, lon2) {
  const toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return EARTH_RADIUS_KM * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

/** Browser geolocation as a promise. Rejects on denial/timeout. */
function getUserLocation() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) {
      reject(new Error('Geolocation not supported'));
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({ lat: pos.coords.latitude, lng: pos.coords.longitude }),
      (err) => reject(err),
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 600000 }
    );
  });
}

/** Fetch daily Tmax/Tmin for a location and date range from Open-Meteo archive. */
async function fetchDailyTemps(lat, lon, startDate, endDate) {
  const url =
    'https://archive-api.open-meteo.com/v1/archive' +
    `?latitude=${lat.toFixed(3)}&longitude=${lon.toFixed(3)}` +
    `&start_date=${startDate}&end_date=${endDate}` +
    '&daily=temperature_2m_max,temperature_2m_min&timezone=auto';
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`Open-Meteo ${resp.status}`);
  const json = await resp.json();
  return json.daily;
}

/** Cumulative GDD curve (one value per day), aligned to daily.time. */
function cumulativeGDD(daily, base = GDD_BASE_C) {
  const tmax = daily.temperature_2m_max || [];
  const tmin = daily.temperature_2m_min || [];
  const cum = [];
  let acc = 0;
  for (let i = 0; i < tmax.length; i++) {
    if (tmax[i] == null || tmin[i] == null) {
      cum.push(acc);
      continue;
    }
    acc += Math.max(0, (tmax[i] + tmin[i]) / 2 - base);
    cum.push(acc);
  }
  return cum;
}

/** First day index where the cumulative curve reaches `target`, else -1. */
function dayReaching(cum, target) {
  for (let i = 0; i < cum.length; i++) {
    if (cum[i] >= target) return i;
  }
  return -1;
}

/**
 * Estimate the season day-shift at the user's location vs the region baseline.
 * Positive = season runs LATER here; negative = EARLIER here.
 * Uses the most recent complete calendar year for a clean full-year curve.
 */
async function computeSeasonShift(userLat, userLng, regionLat, regionLng, climYear) {
  const start = `${climYear}-01-01`;
  const end = `${climYear}-12-31`;

  const [userDaily, regionDaily] = await Promise.all([
    fetchDailyTemps(userLat, userLng, start, end),
    fetchDailyTemps(regionLat, regionLng, start, end),
  ]);

  const userCum = cumulativeGDD(userDaily);
  const regionCum = cumulativeGDD(regionDaily);

  const regionTotal = regionCum[regionCum.length - 1] || 0;
  const userTotal = userCum[userCum.length - 1] || 0;

  // Reference heat sum = halfway through the region's season.
  const ref = regionTotal * 0.5;
  const userDay = dayReaching(userCum, ref);
  const regionDay = dayReaching(regionCum, ref);

  if (userDay < 0 || regionDay < 0) {
    return { shiftDays: 0, userTotal, regionTotal, base: GDD_BASE_C, ok: false };
  }

  return {
    shiftDays: userDay - regionDay,
    userTotal: Math.round(userTotal),
    regionTotal: Math.round(regionTotal),
    base: GDD_BASE_C,
    ok: true,
  };
}

/** Shift a list of ISO week numbers (1–52) by a day offset, wrapping the year. */
function shiftWeeks(weeks, shiftDays) {
  const w = Math.round(shiftDays / 7);
  if (!w) return weeks.slice();
  return weeks.map((week) => ((week - 1 + w + 52) % 52) + 1);
}
