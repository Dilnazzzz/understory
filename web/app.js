/**
 * Understory v0 — Map + season calendar + safety-first detail panel
 */

let data = null;
let map = null;
let selectedSpeciesId = null;
let acknowledgedDeadly = new Set();
let userLocation = null;   // { lat, lng }
let userMarker = null;
let seasonShift = null;    // { shiftDays, userTotal, regionTotal, base, ok }
let suitabilityData = null; // { predStep, grid:[{lat,lng}], species:{id:{suitability,auc,weights}} }
let showSuitability = false;

const WEEK_LABELS = ['J', 'F', 'M', 'A', 'M', 'J', 'J', 'A', 'S', 'O', 'N', 'D'];

async function init() {
  const resp = await fetch('data/species.json');
  data = await resp.json();

  // Optional model layer; tolerate absence (build_sdm.py may not have run).
  try {
    const sResp = await fetch('data/suitability.json');
    if (sResp.ok) suitabilityData = await sResp.json();
  } catch (_) {
    suitabilityData = null;
  }

  // Render the sidebar first so a slow/blocked map CDN never blanks the UI.
  renderSpeciesList();

  try {
    initMap();
  } catch (err) {
    console.error('Map failed to initialize:', err);
    const mapEl = document.getElementById('map');
    if (mapEl) {
      mapEl.innerHTML =
        '<div class="map-error">Map could not load (check your connection). ' +
        'Species list and details still work.</div>';
    }
  }

  document.getElementById('inSeasonOnly').addEventListener('change', () => {
    const filtered = getFilteredSpecies();
    if (selectedSpeciesId && !filtered.some(s => s.id === selectedSpeciesId)) {
      closeDetail();
    }
    renderSpeciesList();
    updateMapLayer(selectedSpeciesId);
  });
  document.getElementById('close-detail').addEventListener('click', closeDetail);
  document.getElementById('locate-btn').addEventListener('click', handleLocate);

  // Deep link: #<species-id> opens that species (shareable, also drives tests).
  const hashId = decodeURIComponent(location.hash.replace(/^#/, ''));
  if (hashId && data.species.some((s) => s.id === hashId)) {
    showDetail(hashId);
    selectedSpeciesId = hashId;
    renderSpeciesList();
  }
}

// --- Location + local season ---------------------------------------------

async function handleLocate() {
  const btn = document.getElementById('locate-btn');
  btn.disabled = true;
  setLocateStatus('Locating…');

  try {
    userLocation = await getUserLocation();
    addUserMarker();
    if (map) map.flyTo({ center: [userLocation.lng, userLocation.lat], zoom: 11 });

    // Show distances immediately; season shift loads after.
    setLocateStatus('Calculating local season…');
    renderSpeciesList();
    if (selectedSpeciesId) showDetail(selectedSpeciesId);

    await loadSeasonShift();
    setLocateStatus(formatShiftStatus());
    renderSpeciesList();
    if (selectedSpeciesId) showDetail(selectedSpeciesId);
  } catch (err) {
    console.error('locate failed', err);
    const denied = err && err.code === 1;
    setLocateStatus(denied ? 'Location permission denied.' : 'Could not get your location.');
  } finally {
    btn.disabled = false;
  }
}

async function loadSeasonShift() {
  const [west, south, east, north] = data.region.bbox;
  const regionLat = (south + north) / 2;
  const regionLng = (west + east) / 2;
  const climYear = new Date().getFullYear() - 1;
  try {
    seasonShift = await computeSeasonShift(
      userLocation.lat, userLocation.lng, regionLat, regionLng, climYear
    );
  } catch (err) {
    console.error('season shift failed', err);
    seasonShift = null;
  }
}

function setLocateStatus(text) {
  const el = document.getElementById('locate-status');
  if (!el) return;
  el.textContent = text;
  el.classList.remove('hidden');
}

function formatShiftStatus() {
  if (!seasonShift || !seasonShift.ok) return 'Located. (Local season unavailable.)';
  const d = seasonShift.shiftDays;
  if (d === 0) return 'Located. Season here ≈ regional average.';
  const dir = d < 0 ? 'earlier' : 'later';
  return `Located. Season here ≈ ${Math.abs(d)} days ${dir} than regional avg.`;
}

function addUserMarker() {
  if (!map) return;
  if (userMarker) userMarker.remove();
  userMarker = new maplibregl.Marker({ color: '#ffb74d' })
    .setLngLat([userLocation.lng, userLocation.lat])
    .setPopup(new maplibregl.Popup().setHTML('<strong>You are here</strong>'))
    .addTo(map);
}

function nearestHexKm(species) {
  if (!userLocation || !species.hexes || !species.hexes.length) return null;
  let min = Infinity;
  for (const h of species.hexes) {
    const d = haversineKm(userLocation.lat, userLocation.lng, h.lat, h.lng);
    if (d < min) min = d;
  }
  return min;
}

function formatKm(km) {
  if (km == null) return '';
  return km < 10 ? `${km.toFixed(1)} km` : `${Math.round(km)} km`;
}

// Localize a species' season using the GDD day-shift. Returns null if no shift.
function localizedSeason(season) {
  if (!seasonShift || !seasonShift.ok) return null;
  const active = shiftWeeks(season.activeWeeks, seasonShift.shiftDays);
  const peak = shiftWeeks(season.peakWeeks, seasonShift.shiftDays);
  const cur = getISOWeek(new Date());
  const nearby = new Set([cur - 1, cur, cur + 1].map((x) => ((x - 1 + 52) % 52) + 1));
  return {
    activeWeeks: active,
    peakWeeks: peak,
    inSeasonNow: active.some((w) => nearby.has(w)),
  };
}

function initMap() {
  const [west, south, east, north] = data.region.bbox;

  map = new maplibregl.Map({
    container: 'map',
    style: {
      version: 8,
      sources: {
        osm: {
          type: 'raster',
          tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
          tileSize: 256,
          attribution: '&copy; OpenStreetMap contributors',
        },
      },
      layers: [{ id: 'osm', type: 'raster', source: 'osm' }],
    },
    center: [(west + east) / 2, (south + north) / 2],
    zoom: 9,
  });

  map.addControl(new maplibregl.NavigationControl(), 'top-right');

  map.on('load', () => {
    registerMapHandlers();
    updateMapLayer(null);
  });
}

function getFilteredSpecies() {
  const inSeasonOnly = document.getElementById('inSeasonOnly').checked;
  let list = data.species.filter(s => {
    const effective = localizedSeason(s.season) || s.season;
    if (inSeasonOnly && !effective.inSeasonNow) return false;
    return true;
  });

  // When located, surface the closest patches first.
  if (userLocation) {
    list = list.slice().sort((a, b) => {
      const da = nearestHexKm(a);
      const db = nearestHexKm(b);
      return (da ?? Infinity) - (db ?? Infinity);
    });
  }
  return list;
}

function renderSpeciesList() {
  const list = document.getElementById('species-list');
  const filtered = getFilteredSpecies();
  list.innerHTML = '';

  filtered.forEach(species => {
    const li = document.createElement('li');
    li.className = 'species-item' + (species.id === selectedSpeciesId ? ' active' : '');
    li.dataset.id = species.id;

    const local = localizedSeason(species.season);
    const effectiveSeason = local || species.season;
    const seasonBadge = effectiveSeason.inSeasonNow
      ? '<span class="badge in-season">In season</span>'
      : '<span class="badge out-season">Off season</span>';

    const km = nearestHexKm(species);
    const distBadge = km != null
      ? `<span class="badge dist">📍 ${formatKm(km)}</span>`
      : '';

    li.innerHTML = `
      <div class="species-name">${species.commonName}</div>
      <div class="species-scientific">${species.scientificName}</div>
      ${seasonBadge}${distBadge}
    `;

    li.addEventListener('click', () => selectSpecies(species.id));
    list.appendChild(li);
  });
}

function selectSpecies(id) {
  selectedSpeciesId = id;
  renderSpeciesList();
  updateMapLayer(id);
  showDetail(id);
}

function updateMapLayer(speciesId) {
  if (!map || !map.isStyleLoaded()) return;

  // Remove existing layers/sources
  ['hex-fill', 'hex-outline'].forEach(layerId => {
    if (map.getLayer(layerId)) map.removeLayer(layerId);
  });
  if (map.getSource('hexes')) map.removeSource('hexes');

  // Predicted-suitability surface sits UNDER the observation hexes.
  if (showSuitability && speciesId) {
    renderSuitabilityLayer(speciesId);
  } else {
    removeSuitabilityLayer();
  }

  const speciesList = speciesId
    ? data.species.filter(s => s.id === speciesId)
    : getFilteredSpecies();

  const features = [];
  let maxCount = 1;

  speciesList.forEach(species => {
    species.hexes.forEach(hex => {
      maxCount = Math.max(maxCount, hex.count);
      features.push({
        type: 'Feature',
        properties: {
          speciesId: species.id,
          commonName: species.commonName,
          count: hex.count,
          recentCount: hex.recentCount ?? 0,
          lastSeen: hex.lastSeen ?? null,
          sampleIds: JSON.stringify(hex.sampleIds || []),
          intensity: hex.count / maxCount,
        },
        geometry: {
          type: 'Point',
          coordinates: [hex.lng, hex.lat],
        },
      });
    });
  });

  if (features.length === 0) return;

  map.addSource('hexes', {
    type: 'geojson',
    data: { type: 'FeatureCollection', features },
  });

  map.addLayer({
    id: 'hex-fill',
    type: 'circle',
    source: 'hexes',
    paint: {
      'circle-radius': [
        'interpolate', ['linear'], ['get', 'count'],
        1, 8,
        10, 16,
        50, 28,
      ],
      'circle-color': [
        'interpolate', ['linear'], ['get', 'intensity'],
        0, 'rgba(124, 179, 66, 0.2)',
        0.5, 'rgba(124, 179, 66, 0.5)',
        1, 'rgba(174, 213, 129, 0.85)',
      ],
      'circle-stroke-width': 1,
      'circle-stroke-color': 'rgba(255,255,255,0.3)',
    },
  });

  map.addLayer({
    id: 'hex-outline',
    type: 'circle',
    source: 'hexes',
    paint: {
      'circle-radius': 0,
    },
  });
}

// --- Predicted suitability surface (SDM) ---------------------------------

function buildSuitabilityFeatures(speciesId) {
  if (!suitabilityData || !suitabilityData.species[speciesId]) return null;
  const model = suitabilityData.species[speciesId];
  const grid = suitabilityData.grid;
  const half = (suitabilityData.predStep || 0.075) / 2;

  const features = grid.map((cell, i) => ({
    type: 'Feature',
    properties: { suit: model.suitability[i] },
    geometry: {
      type: 'Polygon',
      coordinates: [[
        [cell.lng - half, cell.lat - half],
        [cell.lng + half, cell.lat - half],
        [cell.lng + half, cell.lat + half],
        [cell.lng - half, cell.lat + half],
        [cell.lng - half, cell.lat - half],
      ]],
    },
  }));
  return { type: 'FeatureCollection', features };
}

function renderSuitabilityLayer(speciesId) {
  if (!map || !map.isStyleLoaded()) return;
  removeSuitabilityLayer();
  const fc = buildSuitabilityFeatures(speciesId);
  if (!fc) return;

  map.addSource('suitability', { type: 'geojson', data: fc });
  map.addLayer({
    id: 'suitability-fill',
    type: 'fill',
    source: 'suitability',
    paint: {
      'fill-color': [
        'interpolate', ['linear'], ['get', 'suit'],
        0.0, 'rgba(38, 50, 30, 0)',
        0.3, 'rgba(85, 139, 47, 0.18)',
        0.6, 'rgba(124, 179, 66, 0.45)',
        1.0, 'rgba(174, 213, 129, 0.7)',
      ],
      'fill-opacity': 0.8,
    },
  });
}

function removeSuitabilityLayer() {
  if (!map) return;
  if (map.getLayer('suitability-fill')) map.removeLayer('suitability-fill');
  if (map.getSource('suitability')) map.removeSource('suitability');
}

// Register map click handlers once
function registerMapHandlers() {
  map.on('click', 'hex-fill', (e) => {
    const props = e.features[0].properties;
    let ids = [];
    try { ids = JSON.parse(props.sampleIds || '[]'); } catch (_) {}

    const lastSeen = props.lastSeen
      ? `<div class="popup-meta">Most recent: ${props.lastSeen}</div>`
      : '';
    const recent = props.recentCount
      ? `<div class="popup-meta">${props.recentCount} in the last 10 years</div>`
      : '';
    const evidence = ids.length
      ? `<div class="popup-links">Verify on GBIF: ${ids
          .map((id, i) => `<a href="https://www.gbif.org/occurrence/${id}" target="_blank" rel="noopener">#${i + 1}</a>`)
          .join(' ')}</div>`
      : '';

    new maplibregl.Popup()
      .setLngLat(e.lngLat)
      .setHTML(
        `<strong>${props.commonName}</strong>` +
        `<div class="popup-meta">${props.count} observations in this area</div>` +
        lastSeen + recent + evidence
      )
      .addTo(map);
  });

  map.on('mouseenter', 'hex-fill', () => { map.getCanvas().style.cursor = 'pointer'; });
  map.on('mouseleave', 'hex-fill', () => { map.getCanvas().style.cursor = ''; });
}

function hasDeadlyLookalike(species) {
  const lookalikes = species.edibility?.lookalikes || [];
  return lookalikes.some(l => l.risk === 'deadly');
}

function showDetail(id) {
  const species = data.species.find(s => s.id === id);
  if (!species) return;

  const panel = document.getElementById('detail-panel');
  const content = document.getElementById('detail-content');
  panel.classList.remove('hidden');

  const ed = species.edibility || {};
  const deadly = hasDeadlyLookalike(species);
  const needsAck = deadly && !acknowledgedDeadly.has(id);

  // Build lookalike warnings
  const lookalikeHtml = (ed.lookalikes || []).map(l => {
    const cls = l.risk === 'deadly' ? 'deadly' : '';
    return `<div class="lookalike-item ${cls}">
      <strong>${l.name}</strong> (${l.risk})
      <div>${l.note}</div>
    </div>`;
  }).join('');

  const deadlyBanner = deadly ? `
    <div class="warning-banner deadly">
      <strong>Deadly lookalike possible</strong>
      This species has toxic lookalikes. You must confirm identification beyond this app.
      ${lookalikeHtml}
    </div>
  ` : '';

  const ackButton = needsAck ? `
    <button class="ack-button" id="ack-deadly">
      I understand the deadly lookalike risk — show harvest info
    </button>
  ` : '';

  const harvestHidden = needsAck ? 'hidden' : '';

  content.innerHTML = `
    <div class="detail-title">${species.commonName}</div>
    <div class="detail-scientific">${species.scientificName}</div>
    <div class="detail-meta">
      ${species.occurrenceCount} observations ·
      ${species.hexes.length} map areas${(() => {
        const km = nearestHexKm(species);
        return km != null ? ` · 📍 nearest patch ~${formatKm(km)}` : '';
      })()}
    </div>

    ${deadlyBanner}
    ${ackButton}

    <div class="harvest-section ${harvestHidden}" id="harvest-info">
      ${renderSeasonSection(species)}

      <div class="section">
        <h3>Edible parts</h3>
        <p>${(ed.edibleParts || []).join(', ') || 'See field guide'}</p>
      </div>

      <div class="section">
        <h3>Preparation</h3>
        <p>${ed.preparation || 'Consult a field guide'}</p>
      </div>

      ${ed.hazards ? `<div class="section"><h3>Hazards</h3><p>${ed.hazards}</p></div>` : ''}

      ${!deadly && lookalikeHtml ? `<div class="section"><h3>Lookalikes</h3>${lookalikeHtml}</div>` : ''}

      ${renderAssociations(species)}

      ${renderModelSection(species)}

      ${renderProvenance(species)}

      <div class="section">
        <h3>Verify</h3>
        <p style="color:var(--warn)">
          Always confirm with a field guide or expert. This app is not a sole ID authority.
        </p>
      </div>
    </div>
  `;

  if (needsAck) {
    document.getElementById('ack-deadly').addEventListener('click', () => {
      acknowledgedDeadly.add(id);
      showDetail(id);
    });
  }

  // Walkable graph: clicking an associated species navigates to it.
  content.querySelectorAll('[data-assoc-id]').forEach((el) => {
    el.addEventListener('click', () => selectSpecies(el.dataset.assocId));
  });

  const suitToggle = document.getElementById('suit-toggle');
  if (suitToggle) {
    suitToggle.addEventListener('change', () => {
      showSuitability = suitToggle.checked;
      updateMapLayer(selectedSpeciesId);
    });
  }
}

const DRIVER_LABELS = {
  elevation: 'elevation',
  temp: 'temperature',
  tempSeasonality: 'temperature seasonality',
  precip: 'precipitation',
};

function renderModelSection(species) {
  if (!suitabilityData || !suitabilityData.species[species.id]) return '';
  const m = suitabilityData.species[species.id];

  const driver = Object.entries(m.weights)
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))[0];
  const driverDir = driver[1] > 0 ? 'higher' : 'lower';
  const driverLabel = DRIVER_LABELS[driver[0]] || driver[0];

  return `
    <div class="section model">
      <h3>Predicted range <span class="tag-model">model</span></h3>
      <label class="toggle model-toggle">
        <input type="checkbox" id="suit-toggle" ${showSuitability ? 'checked' : ''}>
        <span>Show suitability surface on map</span>
      </label>
      <p class="model-note">
        Used-vs-available logistic model over elevation + climate
        (AUC ${m.auc ?? '—'}, ${m.presenceCells} presence cells).
        Strongest driver: <strong>${driverDir} ${driverLabel}</strong>.
        Predicts climatically suitable ground — a hypothesis, not confirmed sightings.
      </p>
    </div>
  `;
}

function renderAssociations(species) {
  const assocs = species.associations || [];
  if (!assocs.length) return '';

  const rows = assocs.map((a) => {
    const pct = Math.round(a.conditional * 100);
    const seasonTag = a.seasonOverlap >= 0.5
      ? '<span class="assoc-season">same season</span>'
      : '';
    return `
      <button class="assoc-item" data-assoc-id="${a.id}">
        <span class="assoc-name">${a.commonName} ${seasonTag}</span>
        <span class="assoc-stats">
          <strong>${pct}%</strong> of its areas
          <span class="assoc-lift" title="How much more often than chance">·&nbsp;${a.lift}× chance</span>
        </span>
      </button>`;
  }).join('');

  return `
    <div class="section associations">
      <h3>Often found nearby</h3>
      <p class="assoc-intro">
        Where you find ${species.commonName.toLowerCase()}, these tend to grow close by
        (from spatial co-occurrence; tap to explore).
      </p>
      ${rows}
    </div>
  `;
}

function renderProvenance(species) {
  const p = species.provenance || {};
  const range = p.yearRange ? `${p.yearRange[0]}–${p.yearRange[1]}` : '—';
  const available = p.totalAvailable
    ? ` of ${p.totalAvailable.toLocaleString()} in this region`
    : '';
  const datasets = p.datasetCount
    ? `${p.datasetCount} dataset${p.datasetCount === 1 ? '' : 's'}`
    : '—';
  const gbifLink = p.gbifTaxonUrl
    ? `<a href="${p.gbifTaxonUrl}" target="_blank" rel="noopener">View on GBIF →</a>`
    : '';

  return `
    <div class="section provenance">
      <h3>Data &amp; evidence</h3>
      <ul class="prov-list">
        <li><span>Records sampled</span><strong>${(p.recordCount ?? 0).toLocaleString()}${available}</strong></li>
        <li><span>Years sampled</span><strong>${range}</strong></li>
        <li><span>Recent (last 10y)</span><strong>${(p.recentCount ?? 0).toLocaleString()}</strong></li>
        <li><span>Sources</span><strong>${datasets}</strong></li>
      </ul>
      <p class="prov-note">
        Maps show where this species was <em>observed and reported</em>, not everywhere it grows.
        When thousands of records exist we sample the most recent. Records cluster near trails,
        towns, and active observers (sampling bias). ${gbifLink}
      </p>
    </div>
  `;
}

function renderSeasonSection(species) {
  const local = localizedSeason(species.season);
  const displaySeason = local || species.season;
  const totalRecords = species.season.histogram.reduce((a, b) => a + b, 0);

  const verdict = displaySeason.inSeasonNow ? 'Likely in season' : 'Likely off season';
  const scope = local ? 'at your location this week' : 'this week (regional)';

  let gddNote = '';
  if (local && seasonShift && seasonShift.ok) {
    const d = seasonShift.shiftDays;
    if (d === 0) {
      gddNote = `<p class="gdd-note">Local heat accumulation ≈ regional average (base ${seasonShift.base}°C).</p>`;
    } else {
      const dir = d < 0 ? 'earlier' : 'later';
      const speed = d < 0 ? 'faster' : 'slower';
      gddNote = `<p class="gdd-note">
        Shifted ~${Math.abs(d)} days ${dir}: your location accumulates
        growing-degree-days ${speed} than the regional average (base ${seasonShift.base}°C).
      </p>`;
    }
  }

  return `
    <div class="section">
      <h3>Season ${local ? '<span class="tag-local">local</span>' : ''}</h3>
      ${renderSeasonStrip(displaySeason)}
      <div class="season-labels">
        ${WEEK_LABELS.map(m => `<span>${m}</span>`).join('')}
      </div>
      <p class="season-verdict">
        ${verdict} ${scope}
        <span class="muted-small">· from ${totalRecords} dated records</span>
      </p>
      ${gddNote}
    </div>
  `;
}

function renderSeasonStrip(season) {
  const currentWeek = getISOWeek(new Date());
  const activeSet = new Set(season.activeWeeks);
  const peakSet = new Set(season.peakWeeks);

  let html = '<div class="season-strip">';
  for (let w = 1; w <= 52; w++) {
    let cls = 'season-week';
    if (peakSet.has(w)) cls += ' peak';
    else if (activeSet.has(w)) cls += ' active';
    if (w === currentWeek) cls += ' current';
    html += `<div class="${cls}" title="Week ${w}"></div>`;
  }
  html += '</div>';
  return html;
}

function getISOWeek(date) {
  const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  d.setUTCDate(d.getUTCDate() + 4 - (d.getUTCDay() || 7));
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  return Math.ceil(((d - yearStart) / 86400000 + 1) / 7);
}

function closeDetail() {
  selectedSpeciesId = null;
  document.getElementById('detail-panel').classList.add('hidden');
  renderSpeciesList();
  updateMapLayer(null);
}

init();
