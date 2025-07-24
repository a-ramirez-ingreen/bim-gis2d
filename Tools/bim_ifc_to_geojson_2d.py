import ifcopenshell
import ifcopenshell.geom
import json
import os
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union
import numpy as np

# Este transformer se define dinámicamente desde app.py
transformer = None

def set_transformer(custom_transformer):
    global transformer
    transformer = custom_transformer

def load_ifc(file_path):
    return ifcopenshell.open(file_path)

def get_entity_types(ifc_model):
    types = {entity.is_a() for entity in ifc_model.by_type("IfcProduct")}
    types = sorted(types)
    types.append("IfcProduct")
    return types

def get_entities_with_geometry(ifc_model, entity_type):
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    entities = []

    target = ifc_model.by_type("IfcProduct") if entity_type == "IfcProduct" else ifc_model.by_type(entity_type)

    for entity in target:
        try:
            shape = ifcopenshell.geom.create_shape(settings, entity)
            if shape:
                entities.append(entity)
        except:
            continue
    return entities

def extract_clean_geometry_2D(entities):
    if transformer is None:
        raise ValueError("El transformer de coordenadas no está definido. Asegúrate de configurarlo desde app.py.")

    geojson_features = []
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)

    for entity in entities:
        try:
            shape = ifcopenshell.geom.create_shape(settings, entity)
            faces = shape.geometry.faces
            verts = shape.geometry.verts

            polygons = []
            unique_triangles = set()

            for i in range(0, len(faces), 3):
                coords = []
                for j in range(3):
                    x, y, _ = verts[faces[i + j] * 3: faces[i + j] * 3 + 3]
                    lon, lat = transformer.transform(x, y)
                    coords.append([lon, lat])

                if coords[0] != coords[-1]:
                    coords.append(coords[0])

                key = tuple(map(tuple, sorted(coords)))
                if key not in unique_triangles:
                    unique_triangles.add(key)
                    polygons.append(Polygon(coords))

            full_shape = unary_union(polygons) if len(polygons) > 1 else (polygons[0] if polygons else None)

            if full_shape and full_shape.is_valid:
                coordinates = (
                    [[list(p.exterior.coords) for p in full_shape.geoms]]
                    if isinstance(full_shape, MultiPolygon)
                    else [list(full_shape.exterior.coords)]
                )

                geojson_features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "MultiPolygon" if isinstance(full_shape, MultiPolygon) else "Polygon",
                        "coordinates": coordinates
                    },
                    "properties": {
                        "GlobalId": entity.GlobalId
                    }
                })
        except:
            continue
    return geojson_features

def calculate_centroids(features):
    centroids = []
    for feature in features:
        coords = feature["geometry"].get("coordinates", [])
        while isinstance(coords, list) and isinstance(coords[0], list):
            coords = coords[0]
        if len(coords) < 3:
            continue
        if coords[0] != coords[-1]:
            coords.append(coords[0])
        try:
            polygon = Polygon(coords)
            if polygon.is_valid:
                centroid = polygon.centroid
                centroids.append({
                    "GlobalId": feature["properties"]["GlobalId"],
                    "centroid": (centroid.x, centroid.y)
                })
        except:
            continue
    return centroids

def extract_ifc_properties(ifc_model, entity_type):
    props = []
    for entity in ifc_model.by_type(entity_type):
        obj = {"IFC_ID": entity.GlobalId, "IFC_Type": entity.is_a()}
        for rel in ifc_model.by_type("IfcRelDefinesByProperties"):
            if rel.RelatedObjects and entity in rel.RelatedObjects:
                pset = rel.RelatingPropertyDefinition
                if pset.is_a("IfcPropertySet"):
                    for prop in pset.HasProperties:
                        if prop.is_a("IfcPropertySingleValue"):
                            val = prop.NominalValue
                            obj[prop.Name] = val.wrappedValue if val else "N/A"
        props.append(obj)
    return props

def build_geojson(features, centroids, properties, selected_props):
    enriched = []
    for feat in features:
        gid = feat["properties"]["GlobalId"]
        prop = next((p for p in properties if p["IFC_ID"] == gid), {})
        centroid = next((c for c in centroids if c["GlobalId"] == gid), {}).get("centroid")
        filtered = {k: prop.get(k, "N/A") for k in selected_props}
        filtered["centroid"] = centroid
        feat["properties"].update(filtered)
        enriched.append(feat)
    return {
        "type": "FeatureCollection",
        "features": enriched
    }
