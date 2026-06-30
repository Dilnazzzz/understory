/**
 * Understory v0 — Map + season calendar + safety-first detail panel
 */

let data = null;
let map = null;
let selectedSpeciesId = null;
let acknowledgedDeadly = new Set();

const WEEK_LABELS = ['J', 'F', 'M', 'A', 'M', 'J', 'J', 'A', 'S', 'O', 'N', 'D'];

async function init() {
  const resp = await fetch('data/species.json');
  data = await resp.json();

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
  return data.species.filter(s => {
    if (inSeasonOnly && !s.season.inSeasonNow) return false;
    return true;
  });
}

function renderSpeciesList() {
  const list = document.getElementById('species-list');
  const filtered = getFilteredSpecies();
  list.innerHTML = '';

  filtered.forEach(species => {
    const li = document.createElement('li');
    li.className = 'species-item' + (species.id === selectedSpeciesId ? ' active' : '');
    li.dataset.id = species.id;

    const seasonBadge = species.season.inSeasonNow
      ? '<span class="badge in-season">In season</span>'
      : '<span class="badge out-season">Off season</span>';

    li.innerHTML = `
      <div class="species-name">${species.commonName}</div>
      <div class="species-scientific">${species.scientificName}</div>
      ${seasonBadge}
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
      ${species.hexes.length} map areas
    </div>

    ${deadlyBanner}
    ${ackButton}

    <div class="harvest-section ${harvestHidden}" id="harvest-info">
      <div class="section">
        <h3>Season</h3>
        ${renderSeasonStrip(species.season)}
        <div class="season-labels">
          ${WEEK_LABELS.map(m => `<span>${m}</span>`).join('')}
        </div>
        <p style="margin-top:0.5rem;font-size:0.8rem;color:var(--muted)">
          ${species.season.inSeasonNow ? 'Likely in season this week' : 'Likely off season this week'}
          (derived from ${species.season.histogram.reduce((a,b)=>a+b,0)} dated records)
        </p>
      </div>

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
