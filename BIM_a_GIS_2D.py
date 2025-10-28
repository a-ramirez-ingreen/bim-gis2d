import streamlit as st
st.set_page_config(page_title="BIM a GIS 2D", layout="wide")

import tempfile
import os
import folium
from folium.plugins import FeatureGroupSubGroup
from streamlit_folium import st_folium
import streamlit.components.v1 as components
import json
from pyproj import Transformer
from Tools import bim_ifc_to_geojson_2d as bimgeo
from gemini_assistant import sugerir_epsg


# --------------------------------------------------
# BOTÓN DE REINICIO
# --------------------------------------------------
st.markdown("""
    <div style='display: flex; justify-content: flex-end;'>
        <form><input type='submit' value='🔁 Reiniciar aplicación' 
        style='padding: 0.5em 1em; border-radius: 6px; border: 1px solid #ccc; 
        background-color: #f44336; color: white; font-weight: bold;'></form>
    </div>
""", unsafe_allow_html=True)


# --------------------------------------------------
# ESTILOS PERSONALIZADOS
# --------------------------------------------------
st.markdown("""
    <style>
    .stDownloadButton button {
        background-color: #28a745;
        color: white;
        border-radius: 5px;
        border: 1px solid #1e7e34;
        padding: 0.5em 1em;
        font-weight: bold;
    }
    .stDownloadButton button:hover {
        background-color: #218838;
        border-color: #1c7430;
    }
    </style>
""", unsafe_allow_html=True)

st.title("🏗️ BIM-GIS 2D Visualizer (Multi-IFC)")


# --------------------------------------------------
# ESTADO INICIAL
# --------------------------------------------------
st.sidebar.header("🔍 Subir archivos IFC")
uploaded_files = st.sidebar.file_uploader(
    "Selecciona uno o varios archivos IFC",
    type=["ifc"],
    accept_multiple_files=True
)

if "ifc_models" not in st.session_state:
    st.session_state.ifc_models = {}
if "geojson_data" not in st.session_state:
    st.session_state.geojson_data = None
if "selected_props" not in st.session_state:
    st.session_state.selected_props = []
if "entity_choices" not in st.session_state:
    st.session_state.entity_choices = []
if "all_props" not in st.session_state:
    st.session_state.all_props = []
if "available_prop_keys" not in st.session_state:
    st.session_state.available_prop_keys = []
if "crs_input" not in st.session_state:
    st.session_state.crs_input = "EPSG:25830 → EPSG:4326"


# --------------------------------------------------
# PASO 1: GEORREFERENCIACIÓN
# --------------------------------------------------
st.sidebar.header("🌍 Georreferenciación del proyecto")
st.session_state.crs_input = st.sidebar.text_input(
    "✍️ Introduce el sistema CRS manual (opcional)",
    value=st.session_state.crs_input,
    key="crs_input_key"
)

ubicacion_texto = st.sidebar.text_input("📍 Describe la ubicación del proyecto (para sugerencia IA)", value="")

if st.sidebar.button("🔎 Sugerir CRS con Gemini") and ubicacion_texto:
    with st.spinner("Consultando IA..."):
        try:
            sugerido = sugerir_epsg(ubicacion_texto)
            st.session_state.crs_input = f"{sugerido} → EPSG:4326"
            st.sidebar.success(f"CRS sugerido: {sugerido}")
        except Exception as e:
            st.sidebar.error(f"No se pudo obtener sugerencia de IA: {e}")

# Configurar transformación CRS
try:
    from_crs, to_crs = [s.strip() for s in st.session_state.crs_input.split("→")]
    transformer = Transformer.from_crs(from_crs, to_crs, always_xy=True)
    bimgeo.set_transformer(transformer)
    st.sidebar.info(f"CRS en uso: {from_crs} → {to_crs}")
except Exception as e:
    st.error(f"❌ Error en configuración CRS: {e}")
    st.stop()


# --------------------------------------------------
# PASO 2: CARGA DE IFC
# --------------------------------------------------
if uploaded_files:
    for uploaded_file in uploaded_files:
        if uploaded_file.name not in st.session_state.ifc_models:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".ifc") as tmp_ifc:
                tmp_ifc.write(uploaded_file.read())
                tmp_ifc_path = tmp_ifc.name
            model = bimgeo.load_ifc(tmp_ifc_path)
            st.session_state.ifc_models[uploaded_file.name] = model


# --------------------------------------------------
# PASO 3: ENTIDADES Y PROPIEDADES
# --------------------------------------------------
if st.session_state.ifc_models:
    entity_types = set()
    for model in st.session_state.ifc_models.values():
        entity_types.update(bimgeo.get_entity_types(model))
    entity_types = sorted(entity_types)

    st.sidebar.header("🏷️ Selección de entidades")
    all_selected = st.sidebar.checkbox("Seleccionar todos", value=False)

    entity_choices = []
    for etype in entity_types:
        default = all_selected or (etype in st.session_state.entity_choices or etype == "IfcProduct")
        if st.sidebar.checkbox(etype, value=default, key=f"etype_{etype}"):
            entity_choices.append(etype)

    if st.sidebar.button("✅ Confirmar entidades"):
        st.session_state.entity_choices = entity_choices
        all_props = []

        for file_name, model in st.session_state.ifc_models.items():
            for entity_choice in st.session_state.entity_choices:
                props = bimgeo.extract_ifc_properties(model, entity_choice)
                for p in props:
                    p["Source_File"] = file_name
                all_props.extend(props)

        all_keys = set()
        for p in all_props:
            all_keys.update(p.keys())

        st.session_state.available_prop_keys = sorted(all_keys)
        st.session_state.all_props = all_props


if st.session_state.available_prop_keys:
    st.sidebar.header("🧩 Selección de propiedades")
    selected_props = []
    for prop in st.session_state.available_prop_keys:
        if st.sidebar.checkbox(
            prop,
            value=(prop in st.session_state.selected_props or prop in ["IFC_ID", "IFC_Type", "Source_File"]),
            key=f"prop_{prop}"
        ):
            selected_props.append(prop)

    if st.sidebar.button("🚀 Procesar y generar GeoJSON"):
        st.session_state.selected_props = selected_props
        all_features, all_centroids = [], []

        for file_name, model in st.session_state.ifc_models.items():
            for entity_choice in st.session_state.entity_choices:
                entities = bimgeo.get_entities_with_geometry(model, entity_choice)
                features = bimgeo.extract_clean_geometry_2D(entities)
                centroids = bimgeo.calculate_centroids(features)
                for f in features:
                    f["properties"]["Source_File"] = file_name
                all_features.extend(features)
                all_centroids.extend(centroids)

        if all_features:
            st.session_state.geojson_data = bimgeo.build_geojson(
                all_features,
                all_centroids,
                st.session_state.all_props or [],
                st.session_state.selected_props or []
            )
            st.success(
                f"✅ Se procesaron {len(all_features)} entidades con geometría "
                f"de {len(st.session_state.ifc_models)} archivos IFC."
            )


# --------------------------------------------------
# PASO 4: MAPA CON CONMUTADOR DE VISTA
# --------------------------------------------------
if st.session_state.geojson_data:
    try:
        first_coords = st.session_state.geojson_data["features"][0]["geometry"]["coordinates"]
        while isinstance(first_coords[0], list):
            first_coords = first_coords[0]
        lat, lon = first_coords[0][1], first_coords[0][0]
    except Exception as e:
        st.error(f"No se pudo determinar el centro del mapa: {e}")
        st.stop()

    st.subheader("🗺️ Modo de visualización del mapa")
    vista = st.radio(
        "Selecciona tipo de fondo:",
        ["Vista normal", "Vista satelital"],
        horizontal=True,
        key="vista_mapa"
    )

    # Crear mapa base
    m = folium.Map(location=[lat, lon], zoom_start=18, max_zoom=24, control_scale=True)

    # Fondo según vista
    if vista == "Vista satelital":
        folium.TileLayer(
            tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            attr="Esri",
            name="🛰️ Satélite (Esri)",
            overlay=False,
            control=False
        ).add_to(m)
    else:
        folium.TileLayer(
            "OpenStreetMap",
            name="🗺️ Calles",
            control=False
        ).add_to(m)

    # Agrupar entidades por archivo
    features_by_file = {}
    for feature in st.session_state.geojson_data["features"]:
        src = feature["properties"].get("Source_File", "Desconocido")
        features_by_file.setdefault(src, []).append(feature)

    base_group = folium.FeatureGroup(name="📦 Entidades IFC", show=True).add_to(m)

    color_palette = [
        "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
        "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"
    ]

    for i, (src, feats) in enumerate(features_by_file.items()):
        color = color_palette[i % len(color_palette)]
        layer = FeatureGroupSubGroup(base_group, name=f"📁 {src}")
        m.add_child(layer)

        for feat in feats:
            folium.GeoJson(
                feat,
                tooltip=folium.GeoJsonTooltip(fields=st.session_state.selected_props),
                style_function=lambda f, color=color: {
                    "fillColor": color,
                    "color": "black",
                    "weight": 1,
                    "fillOpacity": 0.7
                },
                highlight_function=lambda x: {"weight": 3, "fillColor": "#FFFF00"}
            ).add_to(layer)

    # Render mapa en Streamlit
    st_folium(m, use_container_width=True, height=800)

    # Descargar GeoJSON combinado
    st.download_button(
        "📅 Descargar GeoJSON combinado",
        data=json.dumps(st.session_state.geojson_data, indent=2),
        file_name="ifc_multi_to_geojson_2d.geojson",
        mime="application/geo+json"
    )
