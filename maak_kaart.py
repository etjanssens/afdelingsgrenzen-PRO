import requests
import json
import pandas as pd
import folium
import geopandas as gpd
from shapely.ops import unary_union

# PRO brandbook kleuren (exact uit brandboek pagina 35)
PRO_GREEN      = '#00AA00'
PRO_GREEN_50   = '#AAEE77'
PRO_GREEN_25   = '#DDFFDD'
PRO_RED        = '#FF0000'
PRO_RED_50     = '#FFAACC'
PRO_RED_25     = '#FFDDEE'

PALETTE = [PRO_GREEN, PRO_GREEN_50, PRO_GREEN_25, PRO_RED, PRO_RED_50, PRO_RED_25]

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
afdeling_kleur = {afd: PALETTE[i % len(PALETTE)] for i, afd in enumerate(afdelingen_sorted)}

for feature in geo_data['features']:
    geo_naam = feature['properties']['statnaam']
    excel_naam = name_map.get(geo_naam, geo_naam)
    data = gemeente_data.get(excel_naam, {})
    afdeling = data.get('afdeling', 'Onbekend')
    bestuursleden = data.get('bestuursleden', {})
    p = feature['properties']
    p['afdeling'] = afdeling
    p['kleur'] = afdeling_kleur.get(afdeling, '#cccccc')
    p['gemeente_excel'] = excel_naam
    p['i-Voorzitter'] = bestuursleden.get('i-Voorzitter', '')
    p['i-Secretaris'] = bestuursleden.get('i-Secretaris', '')
    p['i-Penningmeester'] = bestuursleden.get('i-Penningmeester', '')
    p['i-Algemeen Bestuurslid'] = bestuursleden.get('i-Algemeen Bestuurslid', '')

gdf = gpd.GeoDataFrame.from_features(geo_data['features'])

afdeling_centroids = {}
for afdeling, group in gdf.groupby('afdeling'):
    if afdeling in ('Onbekend', 'nan'):
        continue
    centroid = unary_union(group.geometry).centroid
    afdeling_centroids[afdeling] = (centroid.y, centroid.x)

afd_dissolved = gdf[gdf['afdeling'] != 'Onbekend'].dissolve(by='afdeling').reset_index()
afd_borders_geojson = json.loads(afd_dissolved[['afdeling', 'geometry']].to_json())

# --- Folium kaart ---
m = folium.Map(
    location=[52.3, 5.3],
    zoom_start=7,
    tiles='CartoDB positron',
    min_zoom=6,
    max_zoom=13,
)

def style_fn(feature):
    return {
        'fillColor': feature['properties'].get('kleur', '#cccccc'),
        'color': 'rgba(255,255,255,0.4)',
        'weight': 0.4,
        'fillOpacity': 0.82,
    }

def highlight_fn(feature):
    return {'fillOpacity': 0.95, 'weight': 0.4, 'color': 'rgba(255,255,255,0.4)'}

geojson_layer = folium.GeoJson(
    geo_data,
    name='Gemeentes',
    style_function=style_fn,
    highlight_function=highlight_fn,
    tooltip=folium.GeoJsonTooltip(
        fields=['statnaam', 'afdeling'],
        aliases=['Gemeente:', 'Afdeling:'],
        sticky=True,
        style=(
            'background-color:#DDFFDD;color:#000;font-family:"Special Gothic Condensed One",'
            '"Barlow Condensed",Arial;font-size:13px;padding:8px 12px;border-radius:0;'
            'border:1px solid #00AA00;box-shadow:none;'
        ),
    ),
)
geojson_layer.add_to(m)

border_layer = folium.GeoJson(
    afd_borders_geojson,
    name='Afdelingsgrenzen',
    style_function=lambda f: {
        'fillOpacity': 0,
        'color': '#111111',
        'weight': 1.8,
        'opacity': 0.38,
    },
)
border_layer.add_to(m)

labels_group = folium.FeatureGroup(name='Afdelingsnamen', show=True)
for afdeling, (lat, lon) in afdeling_centroids.items():
    folium.Marker(
        [lat, lon],
        icon=folium.DivIcon(
            html=(
                f'<div style="font-family:\'Special Gothic Condensed One\',\'Barlow Condensed\','
                f'Arial;font-size:11px;font-weight:700;letter-spacing:0.05em;'
                f'color:#111;text-align:center;white-space:nowrap;pointer-events:none;'
                f'text-transform:uppercase;line-height:1.2;'
                f'background:rgba(221,255,221,0.82);padding:1px 5px;">'
                f'{afdeling.upper()}</div>'
            ),
            icon_size=(240, 18),
            icon_anchor=(120, 9),
        )
    ).add_to(labels_group)
labels_group.add_to(m)

folium.LayerControl(collapsed=True).add_to(m)

map_var = m.get_name()
layer_var = geojson_layer.get_name()
border_var = border_layer.get_name()

search_data = [
    {'naam': f['properties']['statnaam'], 'afdeling': f['properties'].get('afdeling', '')}
    for f in geo_data['features']
]
search_json = json.dumps(search_data, ensure_ascii=False)

custom_html = f"""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Special+Gothic+Condensed+One&family=Barlow+Condensed:wght@400;600;700&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>

<style>
  :root {{
    --groen:    {PRO_GREEN};
    --groen-25: {PRO_GREEN_25};
    --rood:     {PRO_RED};
    --font-kop:  'Special Gothic Condensed One', 'Barlow Condensed', Arial, sans-serif;
    --font-body: 'Barlow Condensed', Arial, sans-serif;
  }}
  .leaflet-interactive:focus {{ outline: none !important; }}

  #kaart-titel {{
    position: fixed; top: 12px; left: 50%; transform: translateX(-50%);
    z-index: 1000; background: var(--groen); color: white;
    font-family: var(--font-kop); font-size: 18px;
    letter-spacing: 0.08em; text-transform: uppercase;
    padding: 9px 26px 7px; line-height: 1;
    pointer-events: none; white-space: nowrap;
    box-shadow: 0 2px 10px rgba(0,0,0,0.25);
  }}
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

  #download-btn {{
    position: fixed; top: 66px; left: 12px; z-index: 1000;
    background: var(--rood); color: white; border: none;
    padding: 7px 14px 6px; font-family: var(--font-kop);
    font-size: 13px; letter-spacing: 0.06em; text-transform: uppercase;
    cursor: pointer;
  }}
  #download-btn:hover {{ background: #cc0000; }}
  #download-btn:disabled {{ background: #aaa; cursor: wait; }}

  #attributie {{
    position: fixed; bottom: 6px; left: 10px; z-index: 999;
    font-family: var(--font-body); font-size: 10px;
    color: #555; pointer-events: none;
  }}

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
</style>

<div id="kaart-titel">Afdelingsgrenzen Progressief Nederland</div>
<div id="zoek-container">
  <div id="zoek-wrap">
    <input type="text" id="zoek-input" placeholder="Zoek gemeente of afdeling…" autocomplete="off">
    <button id="zoek-clear">✕</button>
  </div>
  <div id="zoek-resultaten"></div>
</div>
<button id="download-btn">↓ PNG</button>
<div id="attributie">door Emiel Janssens, voor Luuk Mevis</div>

<script>
// Wacht tot alle Folium/Leaflet-scripts zijn uitgevoerd
window.addEventListener('load', function() {{
  var kaart      = window['{map_var}'];
  var geolaag    = window['{layer_var}'];
  var borderLaag = window['{border_var}'];
  var searchData = {search_json};

  var zoekResultaten = [];
  var activeFilter   = null;
  var activePopup    = null;

  // Afdelingsgrenzen niet-interactief (klikken vallen door naar gemeentelaag)
  function disableBorderPointers() {{
    borderLaag.eachLayer(function(l) {{
      var el = l.getElement ? l.getElement() : null;
      if (el) el.style.pointerEvents = 'none';
    }});
  }}
  disableBorderPointers();
  borderLaag.on('add', disableBorderPointers);

  // ── Stijl-helpers ──────────────────────────────────────────────────
  function defaultStyle(feature) {{
    return {{ fillColor: feature.properties.kleur, color: 'rgba(255,255,255,0.4)', weight: 0.4, fillOpacity: 0.82 }};
  }}
  function highlightAfdeling(afd) {{
    geolaag.setStyle(function(f) {{
      return {{ fillColor: f.properties.kleur, fillOpacity: f.properties.afdeling === afd ? 0.97 : 0.07, color: 'rgba(255,255,255,0.4)', weight: 0.4 }};
    }});
  }}
  function resetHighlight() {{ geolaag.setStyle(defaultStyle); }}

  // ── Popup bij klik ──────────────────────────────────────────────────
  geolaag.on('click', function(e) {{
    if (activePopup) {{ activePopup.remove(); activePopup = null; }}
    var p = e.layer.feature.properties;
    var rollen = [
      ['Voorzitter', p['i-Voorzitter']], ['Secretaris', p['i-Secretaris']],
      ['Penningmeester', p['i-Penningmeester']], ['Alg. bestuurslid', p['i-Algemeen Bestuurslid']],
    ].filter(function(r) {{ return r[1] && r[1].trim(); }});
    var el = document.createElement('div');
    el.className = 'gem-popup';
    el.innerHTML =
      '<button class="gem-popup-sluit">✕</button>' +
      '<div class="gem-popup-titel">' + p.statnaam + '</div>' +
      '<div class="gem-popup-afd">' + (p.afdeling || '') + '</div>' +
      (rollen.length
        ? rollen.map(function(r) {{ return '<div class="gem-popup-rij"><b>' + r[0] + ':</b> ' + r[1] + '</div>'; }}).join('')
        : '<div class="gem-popup-leeg">Nog geen bestuursinfo ingevuld</div>');
    el.querySelector('.gem-popup-sluit').onclick = function() {{ el.remove(); activePopup = null; }};
    el.style.left = Math.min(e.originalEvent.clientX + 12, window.innerWidth  - 300) + 'px';
    el.style.top  = Math.min(e.originalEvent.clientY - 10, window.innerHeight - 200) + 'px';
    document.body.appendChild(el);
    activePopup = el;
    L.DomEvent.stopPropagation(e);
  }});
  kaart.on('click', function() {{ if (activePopup) {{ activePopup.remove(); activePopup = null; }} }});

  // ── Zoekfunctie ──────────────────────────────────────────────────────
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
      activeFilter = r.data.afdeling;
      highlightAfdeling(r.data.afdeling);
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

  // ── Download ────────────────────────────────────────────────────────
  document.getElementById('download-btn').addEventListener('click', function() {{
    var btn = this; btn.textContent = '⏳'; btn.disabled = true;
    var mapId = document.querySelector('.leaflet-container').id;
    html2canvas(document.getElementById(mapId), {{ useCORS: true, scale: 2, logging: false }})
      .then(function(canvas) {{
        var a = document.createElement('a');
        a.download = 'afdelingsgrenzen_PRO.png';
        a.href = canvas.toDataURL('image/png');
        a.click();
        btn.textContent = '↓ PNG'; btn.disabled = false;
      }}).catch(function() {{ btn.textContent = '↓ PNG'; btn.disabled = false; }});
  }});

}});
</script>
"""

m.get_root().html.add_child(folium.Element(custom_html))

output = 'afdelingsgrenzen_kaart.html'
m.save(output)
print(f'Kaart opgeslagen: {output}')
print(f'Afdelingen: {len(afdelingen_sorted)}, Labels: {len(afdeling_centroids)}')
