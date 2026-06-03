import requests
import json
import pandas as pd
import folium
import geopandas as gpd
from shapely.ops import unary_union
from shapely.geometry import mapping

PRO_GREEN      = '#00AA00'
PRO_GREEN_50   = '#AAEE77'
PRO_GREEN_25   = '#DDFFDD'
PRO_RED        = '#FF0000'
PRO_RED_50     = '#FFAACC'
PRO_RED_25     = '#FFDDEE'

# --- Data laden ---
url = 'https://cartomap.github.io/nl/wgs84/gemeente_2024.geojson'
geo_data = requests.get(url, timeout=30).json()
df = pd.read_excel('Afdelingsgrenzen PRO.xlsx', sheet_name='Per gemeente')

name_map = {
    "'s-Gravenhage": "s-Gravenhage",
    "'s-Hertogenbosch": "s-Hertogenbosch",
    "Beek (L.)": "Beek",
    "Bergen (L.)": "Bergen (L)",
    "Bergen (NH.)": "Bergen (NH)",
    "Hengelo (O.)": "Hengelo (O)",
    "Laren (NH.)": "Laren",
    "Middelburg (Z.)": "Middelburg",
    "Rijswijk (ZH.)": "Rijswijk",
    "Stein (L.)": "Stein",
}

gemeente_data = {}
for _, row in df.iterrows():
    gemeente = str(row['Gemeente']).strip()
    if gemeente in ('nan', 'Brussel / België', 'Buitenland'):
        continue
    afdeling = str(row['Naam Lokale Afdeling']).strip()
    bestuursleden = {}
    for col in ['i-Voorzitter', 'i-Secretaris', 'i-Penningmeester', 'i-Algemeen Bestuurslid']:
        val = row.get(col, '')
        if pd.notna(val) and str(val).strip() not in ('nan', ''):
            bestuursleden[col] = str(val).strip()
    gemeente_data[gemeente] = {'afdeling': afdeling, 'bestuursleden': bestuursleden}

afdelingen_sorted = sorted(set(d['afdeling'] for d in gemeente_data.values()))

for feature in geo_data['features']:
    geo_naam = feature['properties']['statnaam']
    excel_naam = name_map.get(geo_naam, geo_naam)
    data = gemeente_data.get(excel_naam, {})
    afdeling = data.get('afdeling', 'Onbekend')
    bestuursleden = data.get('bestuursleden', {})
    p = feature['properties']
    p['afdeling'] = afdeling
    p['gemeente_excel'] = excel_naam
    p['i-Voorzitter'] = bestuursleden.get('i-Voorzitter', '')
    p['i-Secretaris'] = bestuursleden.get('i-Secretaris', '')
    p['i-Penningmeester'] = bestuursleden.get('i-Penningmeester', '')
    p['i-Algemeen Bestuurslid'] = bestuursleden.get('i-Algemeen Bestuurslid', '')

gdf = gpd.GeoDataFrame.from_features(geo_data['features'])

# Afdeling centroids
afdeling_centroids = {}
for afdeling, group in gdf.groupby('afdeling'):
    if afdeling in ('Onbekend', 'nan'):
        continue
    centroid = unary_union(group.geometry).centroid
    afdeling_centroids[afdeling] = (centroid.y, centroid.x)

# Afdeling borders: dissolve dan extraheer exterior boundaries als lijnen
afd_dissolved = gdf[gdf['afdeling'] != 'Onbekend'].dissolve(by='afdeling').reset_index()

border_line_features = []
for _, row in afd_dissolved.iterrows():
    geom = row.geometry
    if geom is None or geom.is_empty:
        continue
    if not geom.is_valid:
        geom = geom.buffer(0)
    boundary = geom.boundary
    if not boundary.is_empty:
        border_line_features.append({
            'type': 'Feature',
            'properties': {'afdeling': row['afdeling']},
            'geometry': mapping(boundary),
        })
afd_lines_geojson = json.dumps(
    {'type': 'FeatureCollection', 'features': border_line_features},
    ensure_ascii=False,
)

# Gemeente centroids
gemeente_centroids = {}
for _, row in gdf.iterrows():
    if row.geometry is None or row.geometry.is_empty:
        continue
    naam = row['statnaam']
    c = row.geometry.centroid
    gemeente_centroids[naam] = (c.y, c.x)

# Suppress gemeente label if it overlaps with an afdeling label
gem_to_afd = {f['properties']['statnaam']: f['properties'].get('afdeling', 'Onbekend')
              for f in geo_data['features']}
afd_gem_count = {}
for afd in gem_to_afd.values():
    afd_gem_count[afd] = afd_gem_count.get(afd, 0) + 1

# 'normal'   = toon gecentreerd
# 'offset'   = toon onder de afdelingsnaam (single-gemeente afdeling)
# 'suppress' = verberg (centroïde te dicht bij een andere afdeling)
gemeente_label_mode = {}
for naam, (gem_lat, gem_lon) in gemeente_centroids.items():
    afd = gem_to_afd.get(naam, 'Onbekend')
    if afd != 'Onbekend' and afd_gem_count.get(afd, 0) == 1:
        gemeente_label_mode[naam] = 'offset'
        continue
    show = True
    for _, (afd_lat, afd_lon) in afdeling_centroids.items():
        if abs(gem_lat - afd_lat) < 0.015 and abs(gem_lon - afd_lon) < 0.015:
            show = False
            break
    gemeente_label_mode[naam] = 'normal' if show else 'suppress'

# --- Folium kaart ---
m = folium.Map(
    location=[52.3, 5.3],
    zoom_start=7,
    tiles='CartoDB positron',
    min_zoom=6,
    max_zoom=13,
    zoom_control=False,
)

# ── FeatureGroup 1: Gemeentegrenzen visueel (togglebaar, GEEN interactie) ──
# Alleen voor de zichtbare grijze lijntjes; hover/klik zit op de laag hieronder.
gem_grenzen_fg = folium.FeatureGroup(name='Gemeentegrenzen', show=True)
folium.GeoJson(
    geo_data,
    style_function=lambda f: {
        'fillOpacity': 0,
        'color':       '#888888',
        'weight':      0.65,
        'opacity':     0.45,
    },
).add_to(gem_grenzen_fg)
gem_grenzen_fg.add_to(m)

# De interactielaag en de afdelingsgrenzen worden via pure JavaScript aangemaakt
# (zie custom_html hieronder) zodat ze NIET in de LayerControl verschijnen.

# ── FeatureGroup 2: Gemeentenamen (cursief, groen, 10px) ──
gem_namen_fg = folium.FeatureGroup(name='Gemeentenamen', show=True)
for naam, (lat, lon) in gemeente_centroids.items():
    mode = gemeente_label_mode.get(naam, 'normal')
    if mode == 'suppress':
        continue
    # 'offset': single-gemeente afdeling → toon label onder de afdelingsnaam.
    # icon_anchor y=-22 plaatst bovenkant van het 14px-label 22px onder het coördinaat,
    # de afdelingsnaam staat gecentreerd op het coördinaat (~10px naar beneden → gap ~12px).
    anchor = (80, -22) if mode == 'offset' else (80, 7)
    folium.Marker(
        [lat, lon],
        icon=folium.DivIcon(
            html=(
                f'<div class="gem-label" style="display:inline-block;position:relative;'
                f'left:50%;transform:translateX(-50%);'
                f'font-family:\'Barlow Condensed\',Arial,sans-serif;'
                f'font-size:10px;font-style:italic;color:{PRO_GREEN};'
                f'white-space:nowrap;pointer-events:none;">'
                f'{naam}</div>'
            ),
            icon_size=(160, 14),
            icon_anchor=anchor,
        )
    ).add_to(gem_namen_fg)
gem_namen_fg.add_to(m)

# ── FeatureGroup 3: Afdelingsnamen (vet, hoofdletters, 11px, geen achtergrond) ──
afd_namen_fg = folium.FeatureGroup(name='Afdelingsnamen', show=True)
for afdeling, (lat, lon) in afdeling_centroids.items():
    folium.Marker(
        [lat, lon],
        icon=folium.DivIcon(
            html=(
                f'<div class="afd-label" style="display:inline-block;position:relative;'
                f'left:50%;transform:translateX(-50%);'
                f'font-family:\'Special Gothic Condensed One\',\'Barlow Condensed\','
                f'Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:0.05em;'
                f'color:#fff;white-space:nowrap;pointer-events:none;'
                f'text-transform:uppercase;line-height:1.3;'
                f'background:{PRO_RED};padding:2px 6px;">'
                f'{afdeling.upper()}</div>'
            ),
            icon_size=(220, 20),
            icon_anchor=(110, 10),
        )
    ).add_to(afd_namen_fg)
afd_namen_fg.add_to(m)

# LayerControl toont alleen de drie FeatureGroups hierboven
folium.LayerControl(collapsed=True).add_to(m)

map_var         = m.get_name()
gem_grenzen_var = gem_grenzen_fg.get_name()   # zodat JS de binnenste GeoJSON kan hergebruiken

search_data = [
    {'naam': f['properties']['statnaam'], 'afdeling': f['properties'].get('afdeling', '')}
    for f in geo_data['features']
]
search_json = json.dumps(search_data, ensure_ascii=False)

custom_html = f"""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Special+Gothic+Condensed+One&family=Barlow+Condensed:wght@400;600;700&display=swap" rel="stylesheet">
<!-- Afdelingsgrenzen data (LineStrings) voor JS-laag -->
<script>var _afdBorderData = {afd_lines_geojson};</script>

<style>
  :root {{
    --groen:    {PRO_GREEN};
    --groen-25: {PRO_GREEN_25};
    --rood:     {PRO_RED};
    --font-kop:  'Special Gothic Condensed One', 'Barlow Condensed', Arial, sans-serif;
    --font-body: 'Barlow Condensed', Arial, sans-serif;
  }}
  .leaflet-interactive:focus {{ outline: none !important; }}

  /* ── Toolbar: zoom + / − (linksboven) ── */
  #kaart-toolbar {{
    position: fixed; top: 12px; left: 12px; z-index: 1000;
    display: flex; flex-direction: column; gap: 3px;
  }}
  .toolbar-btn {{
    width: 34px; height: 34px;
    border: 2px solid rgba(0,0,0,0.2); background: white; color: #333;
    font-size: 20px; font-weight: bold; line-height: 1; cursor: pointer;
    display: flex; align-items: center; justify-content: center;
    box-shadow: 0 1px 5px rgba(0,0,0,0.2);
  }}
  .toolbar-btn:hover {{ background: #f0f0f0; }}

  /* ── Titel (bovenaan midden) ── */
  #kaart-titel {{
    position: fixed; top: 12px; left: 50%; transform: translateX(-50%);
    z-index: 1000; background: var(--groen); color: white;
    font-family: var(--font-kop); font-size: 18px;
    letter-spacing: 0.08em; text-transform: uppercase;
    padding: 9px 26px 7px; line-height: 1;
    pointer-events: none; white-space: nowrap;
    box-shadow: 0 2px 10px rgba(0,0,0,0.25);
  }}

  /* ── Zoekbalk ── */
  #zoek-container {{
    position: fixed; top: 60px; left: 50%; transform: translateX(-50%);
    z-index: 1001; width: 340px;
  }}
  #zoek-wrap {{
    display: flex; background: var(--groen-25);
    border: 2px solid var(--groen);
  }}
  #zoek-input {{
    flex: 1; border: none; background: transparent;
    padding: 8px 12px; font-family: var(--font-body);
    font-size: 13px; font-weight: 600; color: #111; outline: none;
  }}
  #zoek-input::placeholder {{ color: #555; }}
  #zoek-clear {{
    border: none; background: none; padding: 0 11px;
    cursor: pointer; font-size: 14px; color: var(--groen); font-weight: bold;
  }}
  #zoek-resultaten {{
    display: none; background: white;
    border: 2px solid var(--groen); border-top: none;
    max-height: 240px; overflow-y: auto;
  }}
  .zoek-item {{
    padding: 8px 12px; cursor: pointer; font-family: var(--font-body);
    font-size: 13px; font-weight: 600; color: #111;
    display: flex; align-items: center; justify-content: space-between;
    border-bottom: 1px solid var(--groen-25);
  }}
  .zoek-item:hover {{ background: var(--groen-25); }}
  .zoek-badge {{
    font-family: var(--font-kop); font-size: 10px;
    letter-spacing: 0.05em; text-transform: uppercase;
    color: white; padding: 2px 6px; flex-shrink: 0; margin-left: 8px;
  }}
  .badge-gem {{ background: #555; }}
  .badge-afd {{ background: var(--groen); }}

  /* ── Attributie ── */
  #attributie {{
    position: fixed; bottom: 6px; left: 10px; z-index: 999;
    font-family: var(--font-body); font-size: 10px;
    color: #555; pointer-events: none;
  }}

  /* ── Popup ── */
  .gem-popup {{
    position: fixed; z-index: 2000;
    background: var(--groen-25); border: 2px solid var(--groen);
    padding: 14px 16px; min-width: 220px; max-width: 280px;
    font-family: var(--font-body); pointer-events: all;
  }}
  .gem-popup-titel {{
    font-family: var(--font-kop); font-size: 17px;
    letter-spacing: 0.05em; text-transform: uppercase;
    color: #111; margin: 0 22px 4px 0; line-height: 1;
  }}
  .gem-popup-afd {{
    color: var(--groen); font-size: 11px; font-weight: 700;
    letter-spacing: 0.04em; text-transform: uppercase; margin-bottom: 10px;
  }}
  .gem-popup-rij {{ font-size: 12px; margin: 3px 0; color: #333; }}
  .gem-popup-rij b {{ color: #111; }}
  .gem-popup-leeg {{ font-size: 11px; color: #777; margin-top: 4px; }}
  .gem-popup-sluit {{
    position: absolute; top: 8px; right: 10px;
    background: none; border: none; font-size: 16px;
    cursor: pointer; color: var(--groen); font-weight: bold;
  }}
  .gem-popup-sluit:hover {{ color: #005500; }}

  /* ── Hover-tooltip (per afdeling) ── */
  #kaart-tooltip {{
    position: fixed; z-index: 1500; display: none;
    background: var(--groen-25); border: 1px solid var(--groen);
    padding: 7px 11px; pointer-events: none;
    box-shadow: 0 1px 5px rgba(0,0,0,0.15);
  }}
  .tip-afd {{
    font-family: var(--font-kop); font-size: 13px;
    text-transform: uppercase; letter-spacing: 0.05em; color: #111;
  }}
  .tip-gem {{
    font-family: var(--font-body); font-size: 11px;
    font-style: italic; color: #555; margin-top: 2px;
  }}

  /* ── Mobiel ── */
  @media (max-width: 640px) {{
    #kaart-titel {{
      font-size: 13px; padding: 6px 14px 5px; top: 8px;
      left: 58px; transform: none; right: 8px; text-align: center;
    }}
    #zoek-container {{
      top: 52px;
      width: calc(100vw - 24px);
      left: 12px; transform: none;
    }}
    #kaart-toolbar {{ top: 8px; left: 8px; }}
    .toolbar-btn {{ width: 38px; height: 38px; font-size: 22px; }}
    .gem-popup {{
      max-width: calc(100vw - 30px);
      left: 10px !important; right: 10px; top: auto !important;
      bottom: 60px;
    }}
    .leaflet-control-layers {{ font-size: 14px; }}
    .leaflet-control-layers-toggle {{ width: 44px; height: 44px; }}
  }}
</style>

<!-- Toolbar linksboven: zoom + / − -->
<div id="kaart-toolbar">
  <button class="toolbar-btn" id="zoom-in"    title="Inzoomen">+</button>
  <button class="toolbar-btn" id="zoom-uit"   title="Uitzoomen">&minus;</button>
</div>

<div id="kaart-titel">Afdelingsgrenzen Progressief Nederland</div>

<div id="zoek-container">
  <div id="zoek-wrap">
    <input type="text" id="zoek-input" placeholder="Zoek gemeente of afdeling&hellip;" autocomplete="off">
    <button id="zoek-clear">&#10005;</button>
  </div>
  <div id="zoek-resultaten"></div>
</div>

<div id="attributie">door Emiel Janssens, voor Luuk Mevis</div>

<script>
window.addEventListener('load', function() {{
  var kaart      = window['{map_var}'];
  var searchData = {search_json};

  var zoekResultaten = [];
  var activePopup    = null;

  // ── Interactielaag via Leaflet JS (niet via Folium → verschijnt niet in LayerControl) ──
  // Hergebruik features van de al-geïnjecteerde gem_grenzen FeatureGroup.
  var _gemFG = window['{gem_grenzen_var}'];
  var _gemGJ;
  _gemFG.eachLayer(function(l) {{ _gemGJ = l; }});
  var geolaag = L.geoJSON(_gemGJ.toGeoJSON(), {{
    style: function(f) {{
      return {{ fillOpacity: 0.001, fillColor: '#888888', color: '#888888', opacity: 0, weight: 0 }};
    }}
  }}).addTo(kaart);

  // ── Afdelingsgrenzen via Leaflet JS: eigen pane boven alle polygoonlagen ──
  kaart.createPane('afdelingBorderPane');
  kaart.getPane('afdelingBorderPane').style.zIndex    = 450;   // boven overlayPane (400)
  kaart.getPane('afdelingBorderPane').style.pointerEvents = 'none';
  L.geoJSON(_afdBorderData, {{
    pane:  'afdelingBorderPane',
    style: function(f) {{
      return {{ color: '#FF77AA', weight: 2.5, opacity: 1.0 }};
    }}
  }}).addTo(kaart);

  // ── Toolbar ─────────────────────────────────────────────────────────────
  document.getElementById('zoom-in') .addEventListener('click', function() {{ kaart.zoomIn();  }});
  document.getElementById('zoom-uit').addEventListener('click', function() {{ kaart.zoomOut(); }});

  // ── Labelgrootte schaalt mee met zoom ────────────────────────────────────
  function updateLabelSizes() {{
    var z = kaart.getZoom();
    var afdSize = Math.max(8,  Math.min(15, 11 + (z - 7) * 1.5));
    var gemSize = Math.max(6,  Math.min(13, 10 + (z - 7) * 1.2));
    document.querySelectorAll('.afd-label').forEach(function(el) {{ el.style.fontSize = afdSize + 'px'; }});
    document.querySelectorAll('.gem-label').forEach(function(el) {{ el.style.fontSize = gemSize + 'px'; }});
  }}
  kaart.on('zoomend', updateLabelSizes);
  updateLabelSizes();

  // ── Hover per afdeling ────────────────────────────────────────────────────
  var hovTip = document.createElement('div');
  hovTip.id  = 'kaart-tooltip';
  hovTip.innerHTML = '<div class="tip-afd"></div><div class="tip-gem"></div>';
  document.body.appendChild(hovTip);

  var hoveredAfd = null, hovTimer = null;
  var stilStijl = {{ fillOpacity: 0.001, fillColor: '#888888', color: '#888888', opacity: 0, weight: 0 }};
  var hovStijl  = {{ fillOpacity: 0.22,  fillColor: '#00AA00', color: '#005500', opacity: 0.4, weight: 0.5 }};

  geolaag.on('mouseover', function(e) {{
    if (hovTimer) {{ clearTimeout(hovTimer); hovTimer = null; }}
    var props = e.layer.feature.properties;
    var afd   = props.afdeling;
    hovTip.querySelector('.tip-gem').textContent = props.statnaam;
    hovTip.style.display = 'block';
    if (afd === hoveredAfd) return;
    hoveredAfd = afd;
    geolaag.eachLayer(function(l) {{
      l.setStyle(l.feature.properties.afdeling === afd ? hovStijl : stilStijl);
    }});
    hovTip.querySelector('.tip-afd').textContent = afd;
  }});

  geolaag.on('mousemove', function(e) {{
    if (hovTip.style.display !== 'none') {{
      hovTip.style.left = Math.min(e.originalEvent.clientX + 14, window.innerWidth  - 260) + 'px';
      hovTip.style.top  = (e.originalEvent.clientY - 10) + 'px';
    }}
  }});

  geolaag.on('mouseout', function(e) {{
    hovTimer = setTimeout(function() {{
      hoveredAfd = null;
      geolaag.eachLayer(function(l) {{ l.setStyle(stilStijl); }});
      hovTip.style.display = 'none';
    }}, 80);
  }});

  // ── Popup bij klik ────────────────────────────────────────────────────────
  geolaag.on('click', function(e) {{
    if (activePopup) {{ activePopup.remove(); activePopup = null; }}
    var p = e.layer.feature.properties;
    var rollen = [
      ['Voorzitter',       p['i-Voorzitter']],
      ['Secretaris',       p['i-Secretaris']],
      ['Penningmeester',   p['i-Penningmeester']],
      ['Alg. bestuurslid', p['i-Algemeen Bestuurslid']],
    ].filter(function(r) {{ return r[1] && r[1].trim(); }});
    var el = document.createElement('div');
    el.className = 'gem-popup';
    el.innerHTML =
      '<button class="gem-popup-sluit">&#10005;</button>' +
      '<div class="gem-popup-titel">' + p.statnaam + '</div>' +
      '<div class="gem-popup-afd">'   + (p.afdeling || '') + '</div>' +
      (rollen.length
        ? rollen.map(function(r) {{
            return '<div class="gem-popup-rij"><b>' + r[0] + ':</b> ' + r[1] + '</div>';
          }}).join('')
        : '<div class="gem-popup-leeg">Nog geen bestuursinfo ingevuld</div>');
    el.querySelector('.gem-popup-sluit').onclick = function() {{ el.remove(); activePopup = null; }};
    el.style.left = Math.min(e.originalEvent.clientX + 12, window.innerWidth  - 300) + 'px';
    el.style.top  = Math.min(e.originalEvent.clientY - 10, window.innerHeight - 200) + 'px';
    document.body.appendChild(el);
    activePopup = el;
    L.DomEvent.stopPropagation(e);
  }});
  kaart.on('click', function() {{ if (activePopup) {{ activePopup.remove(); activePopup = null; }} }});

  // ── Zoekfunctie ──────────────────────────────────────────────────────────
  var zoekInput     = document.getElementById('zoek-input');
  var zoekResultDiv = document.getElementById('zoek-resultaten');

  function renderResultaten() {{
    zoekResultDiv.innerHTML = zoekResultaten.length === 0
      ? '<div class="zoek-item" style="color:#888;cursor:default;">Geen resultaten</div>'
      : zoekResultaten.map(function(r, i) {{
          return '<div class="zoek-item" data-idx="' + i + '">' +
            '<span>' + r.label + '</span>' +
            '<span class="zoek-badge ' + (r.type === 'gemeente' ? 'badge-gem' : 'badge-afd') + '">' +
            (r.type === 'gemeente' ? 'gemeente' : 'afdeling') + '</span></div>';
        }}).join('');
    zoekResultDiv.querySelectorAll('[data-idx]').forEach(function(item) {{
      item.addEventListener('mousedown', function(e) {{
        e.preventDefault();
        selecteerResultaat(parseInt(item.dataset.idx));
      }});
    }});
    zoekResultDiv.style.display = 'block';
  }}

  zoekInput.addEventListener('input', function() {{
    var q = this.value.trim().toLowerCase();
    if (q.length < 2) {{ zoekResultDiv.style.display = 'none'; return; }}
    var results = [], gezien = {{}};
    searchData.forEach(function(item) {{
      if (item.naam.toLowerCase().indexOf(q) !== -1)
        results.push({{ label: item.naam, type: 'gemeente', data: item }});
      if (item.afdeling && item.afdeling.toLowerCase().indexOf(q) !== -1 && !gezien[item.afdeling]) {{
        gezien[item.afdeling] = 1;
        results.push({{ label: item.afdeling, type: 'afdeling', data: item }});
      }}
    }});
    zoekResultaten = results.slice(0, 12);
    renderResultaten();
  }});

  zoekInput.addEventListener('keydown', function(e) {{
    if (e.key === 'Escape') {{ this.value = ''; zoekResultDiv.style.display = 'none'; }}
    if (e.key === 'Enter' && zoekResultaten.length) selecteerResultaat(0);
  }});
  zoekInput.addEventListener('blur', function() {{
    setTimeout(function() {{ zoekResultDiv.style.display = 'none'; }}, 200);
  }});
  document.getElementById('zoek-clear').addEventListener('click', function() {{
    zoekInput.value = ''; zoekResultDiv.style.display = 'none'; zoekResultaten = [];
  }});

  function selecteerResultaat(idx) {{
    var r = zoekResultaten[idx];
    if (!r) return;
    zoekInput.value = r.label;
    zoekResultDiv.style.display = 'none';
    if (r.type === 'gemeente') {{
      zoomNaarGemeente(r.data.naam);
    }} else {{
      zoomNaarAfdeling(r.data.afdeling);
    }}
  }}

  function zoomNaarGemeente(naam) {{
    geolaag.eachLayer(function(layer) {{
      if (layer.feature.properties.statnaam === naam)
        kaart.fitBounds(layer.getBounds(), {{ maxZoom: 12, padding: [80, 80] }});
    }});
  }}
  function zoomNaarAfdeling(afd) {{
    var bounds = null;
    geolaag.eachLayer(function(layer) {{
      if (layer.feature.properties.afdeling === afd) {{
        var b = layer.getBounds();
        bounds = bounds ? bounds.extend(b) : b;
      }}
    }});
    if (bounds) kaart.fitBounds(bounds, {{ padding: [60, 60] }});
  }}


}});
</script>
"""

m.get_root().html.add_child(folium.Element(custom_html))

output = 'afdelingsgrenzen_kaart.html'
m.save(output)
print(f'Kaart opgeslagen: {output}')
print(f'Afdelingen: {len(afdelingen_sorted)}, Afdeling-labels: {len(afdeling_centroids)}')
n_normal  = sum(1 for m in gemeente_label_mode.values() if m == 'normal')
n_offset  = sum(1 for m in gemeente_label_mode.values() if m == 'offset')
n_suppress = sum(1 for m in gemeente_label_mode.values() if m == 'suppress')
print(f'Gemeente-labels: {n_normal} normaal, {n_offset} onder afd-label, {n_suppress} onderdrukt')
