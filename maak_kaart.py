import requests
import json
import pandas as pd
import folium
import geopandas as gpd
from shapely.ops import unary_union

PALETTE = [
    '#00AA00',  # Links groen
    '#AAEE77',  # 50% groen
    '#DDFFDD',  # 25% groen
    '#FF0000',  # Sociaal rood
    '#FFAACC',  # 50% rood
    '#FFDDEE',  # 25% rood
]

# --- Data laden ---
url = 'https://cartomap.github.io/nl/wgs84/gemeente_2024.geojson'
geo_data = requests.get(url, timeout=30).json()
df = pd.read_excel('Afdelingsgrenzen PRO.xlsx', sheet_name='Per gemeente')

# Naam-correcties GeoJSON → Excel
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

# Gemeente → afdeling + bestuursleden
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

# Kleur per afdeling (cyclisch door palet)
afdelingen_sorted = sorted(set(d['afdeling'] for d in gemeente_data.values()))
afdeling_kleur = {afd: PALETTE[i % len(PALETTE)] for i, afd in enumerate(afdelingen_sorted)}

# GeoJSON features verrijken
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

# GeoDataFrame voor berekeningen
gdf = gpd.GeoDataFrame.from_features(geo_data['features'])

# Centroïden per afdeling
afdeling_centroids = {}
for afdeling, group in gdf.groupby('afdeling'):
    if afdeling in ('Onbekend', 'nan'):
        continue
    centroid = unary_union(group.geometry).centroid
    afdeling_centroids[afdeling] = (centroid.y, centroid.x)

# Afdelingsgrenzen: dissolve gemeentes per afdeling → buitengrens
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
        'color': 'white',
        'weight': 0.5,
        'fillOpacity': 0.85,
    }

def highlight_fn(feature):
    return {'fillOpacity': 1.0, 'weight': 1.0, 'color': 'white'}

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
            'background-color:white;color:#333;font-family:Arial;'
            'font-size:13px;padding:8px;border-radius:4px;'
        ),
    ),
)
geojson_layer.add_to(m)

# Afdelingsgrenzen als aparte laag (geen fill, alleen border)
border_layer = folium.GeoJson(
    afd_borders_geojson,
    name='Afdelingsgrenzen',
    style_function=lambda f: {
        'fillOpacity': 0,
        'color': '#1a1a1a',
        'weight': 2.0,
        'opacity': 0.45,
    },
)
border_layer.add_to(m)

# Labels op centroïden
labels_group = folium.FeatureGroup(name='Afdelingsnamen', show=True)
for afdeling, (lat, lon) in afdeling_centroids.items():
    folium.Marker(
        [lat, lon],
        icon=folium.DivIcon(
            html=(
                f'<div style="font-family:Arial;font-size:9px;font-weight:bold;'
                f'color:#111;text-align:center;white-space:nowrap;pointer-events:none;'
                f'text-shadow:0 0 3px white,0 0 4px white,0 0 4px white;">'
                f'{afdeling}</div>'
            ),
            icon_size=(200, 16),
            icon_anchor=(100, 8),
        )
    ).add_to(labels_group)
labels_group.add_to(m)

folium.LayerControl(collapsed=False).add_to(m)

# JS variabelen
map_var = m.get_name()
layer_var = geojson_layer.get_name()
border_var = border_layer.get_name()

# Data voor zoekfunctie
search_data = [
    {
        'naam': f['properties']['statnaam'],
        'afdeling': f['properties'].get('afdeling', ''),
    }
    for f in geo_data['features']
]
search_json = json.dumps(search_data, ensure_ascii=False)

# Legenda items
legend_items = ''.join(
    f'<div class="leg-item" onclick="filterAfdeling(\'{afd.replace(chr(39), chr(92) + chr(39))}\')" '
    f'title="Klik om te filteren">'
    f'<div class="leg-kleur" style="background:{afdeling_kleur[afd]};"></div>'
    f'<span>{afd}</span></div>'
    for afd in afdelingen_sorted
)

custom_html = f"""
<script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>

<style>
  /* Verwijder klik-outline op kaartshapes */
  .leaflet-interactive:focus {{
    outline: none !important;
  }}

  #kaart-titel {{
    position:fixed;top:15px;left:50%;transform:translateX(-50%);
    z-index:1000;background:white;padding:8px 22px;border-radius:6px;
    box-shadow:0 2px 8px rgba(0,0,0,.22);font-family:Arial;font-size:16px;
    font-weight:bold;color:#2d6e27;white-space:nowrap;
  }}
  #zoek-container {{
    position:fixed;top:58px;left:50%;transform:translateX(-50%);
    z-index:1000;font-family:Arial;width:360px;
  }}
  #zoek-wrap {{
    display:flex;gap:6px;background:white;padding:7px 10px;
    border-radius:6px;box-shadow:0 2px 8px rgba(0,0,0,.22);
  }}
  #zoek-input {{
    flex:1;border:1px solid #ccc;border-radius:4px;padding:5px 10px;
    font-size:13px;outline:none;font-family:Arial;
  }}
  #zoek-input:focus {{ border-color:#2d6e27; }}
  #zoek-clear {{
    border:none;background:#eee;border-radius:4px;padding:5px 9px;
    cursor:pointer;font-size:13px;color:#666;
  }}
  #zoek-resultaten {{
    background:white;border-radius:0 0 6px 6px;
    box-shadow:0 4px 8px rgba(0,0,0,.15);
    max-height:220px;overflow-y:auto;display:none;
    border-top:1px solid #eee;
  }}
  .zoek-item {{
    padding:8px 14px;cursor:pointer;font-size:13px;
    display:flex;align-items:center;justify-content:space-between;
    border-bottom:1px solid #f5f5f5;
  }}
  .zoek-item:hover {{ background:#f0f7ee; }}
  .zoek-badge {{
    font-size:10px;color:white;padding:2px 6px;border-radius:3px;
    font-weight:bold;flex-shrink:0;margin-left:8px;
  }}
  .badge-gem {{ background:#555; }}
  .badge-afd {{ background:#2d6e27; }}
  #download-btn {{
    position:fixed;top:15px;left:15px;z-index:1000;
    background:#2d6e27;color:white;border:none;
    padding:8px 15px;border-radius:6px;font-family:Arial;
    font-size:13px;font-weight:bold;cursor:pointer;
    box-shadow:0 2px 6px rgba(0,0,0,.22);
  }}
  #download-btn:hover {{ background:#1c5018; }}
  #download-btn:disabled {{ background:#aaa;cursor:wait; }}
  #attributie {{
    position:fixed;bottom:8px;left:12px;z-index:1000;
    font-family:Arial;font-size:10px;color:#888;
    pointer-events:none;
  }}
  #legenda {{
    position:fixed;bottom:30px;right:15px;z-index:1000;
    background:white;padding:12px 14px;border-radius:8px;
    box-shadow:0 2px 10px rgba(0,0,0,.25);max-height:72vh;
    overflow-y:auto;width:230px;font-family:Arial;
  }}
  #legenda-header {{
    display:flex;justify-content:space-between;align-items:center;
    margin-bottom:8px;border-bottom:2px solid #2d6e27;padding-bottom:6px;
  }}
  #legenda-header strong {{ font-size:13px;color:#2d6e27; }}
  .leg-toggle-btn {{
    border:none;background:none;cursor:pointer;font-size:13px;color:#666;padding:0;
  }}
  .leg-item {{
    display:flex;align-items:center;margin:2px 0;
    cursor:pointer;padding:2px 3px;border-radius:3px;
  }}
  .leg-item:hover {{ background:#f0f7ee; }}
  .leg-kleur {{
    width:14px;height:14px;border-radius:2px;margin-right:7px;
    border:1px solid rgba(0,0,0,.2);flex-shrink:0;
  }}
  .leg-item span {{ font-size:11px;line-height:1.3; }}
  #leg-reset {{
    margin-top:8px;border-top:1px solid #eee;padding-top:7px;
    display:flex;justify-content:center;
  }}
  #leg-reset button {{
    font-size:11px;background:#f0f0f0;border:none;
    border-radius:4px;padding:4px 12px;cursor:pointer;
  }}
  #leg-reset button:hover {{ background:#ddd; }}
  .gem-popup {{
    position:fixed;z-index:2000;background:white;border-radius:8px;
    box-shadow:0 4px 16px rgba(0,0,0,.3);padding:16px 18px;
    min-width:230px;max-width:300px;font-family:Arial;
    pointer-events:all;
  }}
  .gem-popup-titel {{
    font-size:15px;font-weight:bold;color:#1a1a1a;
    margin:0 24px 4px 0;
  }}
  .gem-popup-afd {{
    color:#2d6e27;font-size:12px;margin-bottom:10px;
  }}
  .gem-popup-rij {{
    font-size:12px;margin:4px 0;color:#444;
  }}
  .gem-popup-rij b {{ color:#1a1a1a; }}
  .gem-popup-leeg {{
    font-size:12px;color:#999;font-style:italic;margin-top:4px;
  }}
  .gem-popup-sluit {{
    position:absolute;top:10px;right:12px;background:none;
    border:none;font-size:17px;cursor:pointer;color:#aaa;
    line-height:1;
  }}
  .gem-popup-sluit:hover {{ color:#555; }}
</style>

<div id="kaart-titel">Afdelingsgrenzen Progressief Nederland</div>

<div id="zoek-container">
  <div id="zoek-wrap">
    <input type="text" id="zoek-input" placeholder="Zoek gemeente of afdeling…"
           oninput="zoekHandler()" onkeydown="zoekKeydown(event)" autocomplete="off">
    <button id="zoek-clear" onclick="clearZoek()" title="Wis zoekopdracht">✕</button>
  </div>
  <div id="zoek-resultaten"></div>
</div>

<button id="download-btn" onclick="downloadKaart()">↓ Download PNG</button>

<div id="attributie">door Emiel Janssens, voor Luuk Mevis</div>

<div id="legenda">
  <div id="legenda-header">
    <strong>Afdelingen PRO ({len(afdelingen_sorted)})</strong>
    <button class="leg-toggle-btn" onclick="toggleLegenda()" id="leg-toggle-btn">▼</button>
  </div>
  <div id="legenda-items">{legend_items}</div>
  <div id="leg-reset">
    <button onclick="resetFilter()">Toon alles</button>
  </div>
</div>

<script>
(function() {{
  var kaart = window['{map_var}'];
  var geolaag = window['{layer_var}'];
  var borderLaag = window['{border_var}'];
  var searchData = {search_json};
  var zoekResultaten = [];
  var activePopup = null;

  // Maak afdelingsgrenzen niet-interactief zodat klikken doorvallen naar gemeentelaag
  borderLaag.eachLayer(function(l) {{
    var el = l.getElement ? l.getElement() : null;
    if (el) el.style.pointerEvents = 'none';
  }});
  borderLaag.on('add', function() {{
    borderLaag.eachLayer(function(l) {{
      var el = l.getElement ? l.getElement() : null;
      if (el) el.style.pointerEvents = 'none';
    }});
  }});

  // ── Popup bij klik ──────────────────────────────────────────────
  geolaag.on('click', function(e) {{
    if (activePopup) {{ activePopup.remove(); activePopup = null; }}
    var p = e.layer.feature.properties;
    var rollen = [
      ['Voorzitter', p['i-Voorzitter']],
      ['Secretaris', p['i-Secretaris']],
      ['Penningmeester', p['i-Penningmeester']],
      ['Alg. bestuurslid', p['i-Algemeen Bestuurslid']],
    ].filter(function(r) {{ return r[1] && r[1].trim() !== ''; }});

    var bestuurHtml = rollen.length > 0
      ? rollen.map(function(r) {{
          return '<div class="gem-popup-rij"><b>' + r[0] + ':</b> ' + r[1] + '</div>';
        }}).join('')
      : '<div class="gem-popup-leeg">Nog geen bestuursinfo ingevuld</div>';

    var el = document.createElement('div');
    el.className = 'gem-popup';
    el.innerHTML =
      '<button class="gem-popup-sluit" onclick="this.parentNode.remove()">✕</button>' +
      '<div class="gem-popup-titel">' + p.statnaam + '</div>' +
      '<div class="gem-popup-afd">📍 ' + (p.afdeling || '') + '</div>' +
      bestuurHtml;

    var x = e.originalEvent.clientX;
    var y = e.originalEvent.clientY;
    el.style.left = Math.min(x + 12, window.innerWidth - 320) + 'px';
    el.style.top  = Math.min(y - 12, window.innerHeight - 220) + 'px';
    document.body.appendChild(el);
    activePopup = el;
    L.DomEvent.stopPropagation(e);
  }});

  kaart.on('click', function() {{
    if (activePopup) {{ activePopup.remove(); activePopup = null; }}
  }});

  // ── Zoekfunctie ─────────────────────────────────────────────────
  window.zoekHandler = function() {{
    var q = document.getElementById('zoek-input').value.trim().toLowerCase();
    var div = document.getElementById('zoek-resultaten');
    if (q.length < 2) {{ div.style.display = 'none'; return; }}

    var results = [];
    var afdelingGezien = {{}};
    searchData.forEach(function(item) {{
      if (item.naam.toLowerCase().indexOf(q) >= 0) {{
        results.push({{ label: item.naam, type: 'gemeente', data: item }});
      }}
      if (item.afdeling.toLowerCase().indexOf(q) >= 0 && !afdelingGezien[item.afdeling]) {{
        afdelingGezien[item.afdeling] = true;
        results.push({{ label: item.afdeling, type: 'afdeling', data: item }});
      }}
    }});

    zoekResultaten = results.slice(0, 12);
    if (zoekResultaten.length === 0) {{
      div.innerHTML = '<div class="zoek-item" style="color:#999;cursor:default;">Geen resultaten gevonden</div>';
    }} else {{
      div.innerHTML = zoekResultaten.map(function(r, i) {{
        return '<div class="zoek-item" onclick="selecteerResultaat(' + i + ')">' +
          '<span>' + r.label + '</span>' +
          '<span class="zoek-badge ' + (r.type === 'gemeente' ? 'badge-gem' : 'badge-afd') + '">' +
          r.type + '</span></div>';
      }}).join('');
    }}
    div.style.display = 'block';
  }};

  window.selecteerResultaat = function(idx) {{
    var r = zoekResultaten[idx];
    if (!r) return;
    document.getElementById('zoek-input').value = r.label;
    document.getElementById('zoek-resultaten').style.display = 'none';
    if (r.type === 'gemeente') {{
      zoomNaarGemeente(r.data.naam);
    }} else {{
      filterAfdeling(r.data.afdeling);
    }}
  }};

  window.zoekKeydown = function(e) {{
    if (e.key === 'Escape') {{ clearZoek(); }}
    if (e.key === 'Enter' && zoekResultaten.length > 0) {{ selecteerResultaat(0); }}
  }};

  window.clearZoek = function() {{
    document.getElementById('zoek-input').value = '';
    document.getElementById('zoek-resultaten').style.display = 'none';
    zoekResultaten = [];
  }};

  // ── Afdeling filteren / zoomen ──────────────────────────────────
  window.filterAfdeling = function(afd) {{
    geolaag.setStyle(function(feature) {{
      var match = feature.properties.afdeling === afd;
      return {{
        fillColor: feature.properties.kleur,
        fillOpacity: match ? 0.92 : 0.12,
        color: 'white',
        weight: 0.5,
      }};
    }});
    zoomNaarAfdeling(afd);
  }};

  window.resetFilter = function() {{
    geolaag.setStyle(function(feature) {{
      return {{
        fillColor: feature.properties.kleur,
        color: 'white',
        weight: 0.5,
        fillOpacity: 0.85,
      }};
    }});
    kaart.setView([52.3, 5.3], 7);
  }};

  function zoomNaarGemeente(naam) {{
    geolaag.eachLayer(function(layer) {{
      if (layer.feature.properties.statnaam === naam) {{
        kaart.fitBounds(layer.getBounds(), {{ maxZoom: 12, padding: [60, 60] }});
      }}
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
    if (bounds) kaart.fitBounds(bounds, {{ padding: [50, 50] }});
  }}

  window.zoomNaarGemeente = zoomNaarGemeente;
  window.zoomNaarAfdeling = zoomNaarAfdeling;

  // ── Download PNG ────────────────────────────────────────────────
  window.downloadKaart = function() {{
    var btn = document.getElementById('download-btn');
    btn.textContent = '⏳ Bezig…';
    btn.disabled = true;
    html2canvas(document.getElementById('map'), {{
      useCORS: true,
      scale: 2,
      logging: false,
    }}).then(function(canvas) {{
      var a = document.createElement('a');
      a.download = 'afdelingsgrenzen_PRO.png';
      a.href = canvas.toDataURL('image/png');
      a.click();
      btn.textContent = '↓ Download PNG';
      btn.disabled = false;
    }}).catch(function() {{
      btn.textContent = '↓ Download PNG';
      btn.disabled = false;
    }});
  }};

  // ── Legenda toggle ──────────────────────────────────────────────
  window.toggleLegenda = function() {{
    var items = document.getElementById('legenda-items');
    var reset = document.getElementById('leg-reset');
    var btn   = document.getElementById('leg-toggle-btn');
    var hide  = items.style.display !== 'none';
    items.style.display = hide ? 'none' : 'block';
    reset.style.display = hide ? 'none' : 'flex';
    btn.textContent     = hide ? '▶' : '▼';
  }};

  // Klik buiten zoek sluit resultaten
  document.addEventListener('click', function(e) {{
    if (!e.target.closest('#zoek-container')) {{
      document.getElementById('zoek-resultaten').style.display = 'none';
    }}
  }});

}})();
</script>
"""

m.get_root().html.add_child(folium.Element(custom_html))

output = 'afdelingsgrenzen_kaart.html'
m.save(output)
print(f'Kaart opgeslagen: {output}')
print(f'Afdelingen: {len(afdelingen_sorted)}, Labels: {len(afdeling_centroids)}')
