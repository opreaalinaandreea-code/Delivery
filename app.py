import streamlit as st
import pandas as pd
import numpy as np
import math
import xml.etree.ElementTree as ET
import re  # <-- FIX: Importat corect la începutul fișierului pentru a evita eroarea
from datetime import datetime, timedelta
import io

# --- Page Configuration ---
st.set_page_config(page_title="RoRoute - Planificator My Maps Excel", layout="wide")

# --- Funcție de extragere BULLETPROOF pentru KML (Google My Maps) ---
def parse_kml_flexible(kml_file):
    """
    Scanează flexibil tot fișierul KML fără a depinde de namespace strict
    sau structuri rigide de foldere.
    """
    try:
        kml_content = kml_file.read()
        # Eliminăm namespace-urile din tag-uri pentru a putea căuta curat prin text brut
        utf8_content = kml_content.decode('utf-8', errors='ignore')
        clean_content = re.sub(r'\sxmlns="[^"]+"', '', utf8_content, count=1)
        
        # Dacă eliminarea regex nu a fost ideală, încărcăm conținutul brut direct
        try:
            root = ET.fromstring(clean_content.encode('utf-8'))
        except Exception:
            root = ET.fromstring(kml_content)
            
        records = []
        
        # Căutăm absolut toate elementele Placemark de la orice nivel (căutare globală //)
        for elem in root.iter():
            tag_name = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            
            if tag_name == 'Placemark':
                name_text = ""
                desc_text = ""
                coords_text = ""
                
                for child in elem:
                    child_tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                    if child_tag == 'name' and child.text:
                        name_text = child.text.strip()
                    elif child_tag == 'description' and child.text:
                        desc_text = child.text.strip()
                    elif child_tag == 'Point':
                        for point_child in child:
                            pt_tag = point_child.tag.split('}')[-1] if '}' in point_child.tag else point_child.tag
                            if pt_tag == 'coordinates' and point_child.text:
                                coords_text = point_child.text.strip()
                                
                if coords_text:
                    # Format standard KML: longitudine,latitudine,altitudine
                    parts = coords_text.split(',')
                    if len(parts) >= 2:
                        try:
                            lon = float(parts[0].strip())
                            lat = float(parts[1].strip())
                            
                            records.append({
                                'ID_KML_Potrivire': name_text,
                                'Latitudine': lat,
                                'Longitudine': lon,
                                'Geocoded_address': desc_text if desc_text else "Preluat din My Maps"
                            })
                        except ValueError:
                            pass
                            
        if len(records) > 0:
            return pd.DataFrame(records), None
        else:
            # Căutare directă prin Regex dacă XML parserul a ignorat structura din cauza formatului
            records_regex = []
            placemarks_raw = re.findall(r'<Placemark>.*?</Placemark>', utf8_content, re.DOTALL)
            for pm in placemarks_raw:
                name_m = re.search(r'<name>(.*?)</name>', pm)
                coords_m = re.search(r'<coordinates>(.*?)</coordinates>', pm)
                desc_m = re.search(r'<description>(.*?)</description>', pm)
                
                name_t = name_m.group(1).strip() if name_m else "Fără Nume"
                desc_t = desc_m.group(1).strip() if desc_m else ""
                
                if coords_m:
                    c_parts = coords_m.group(1).strip().split(',')
                    if len(c_parts) >= 2:
                        try:
                            records_regex.append({
                                'ID_KML_Potrivire': name_t,
                                'Latitudine': float(c_parts[1].strip()),
                                'Longitudine': float(c_parts[0].strip()),
                                'Geocoded_address': desc_t if desc_t else "Preluat din My Maps (Regex)"
                            })
                        except ValueError:
                            pass
            if len(records_regex) > 0:
                return pd.DataFrame(records_regex), None
                
            return None, "Nu s-au găsit puncte geografice în fișier. Asigură-te că ai selectat formatul KML la export din My Maps."
    except Exception as e:
        return None, f"Eroare la procesarea fișierului KML: {str(e)}"

# --- Distance Calculation ---
def haversine_distance(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2) or any(math.isnan(x) for x in (lat1, lon1, lat2, lon2)):
        return 999.0
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(delta_lambda/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1-a))

# --- Standardizer / Column Mapper ---
def standardize_orders_df(df):
    df = df.copy()
    original_cols = list(df.columns)
    clean_cols = [str(c).strip() for c in df.columns]
    df.columns = clean_cols
    
    mapping = {
        'ID_Livrare': ['Nr. Comanda', 'ID_Livrare', 'Id', 'ID', 'Cod'],
        'Client': ['First Name (Shipping)', 'Client', 'Nume', 'Name', 'Destinatar'],
        'Telefon': ['Phone (Billing)', 'Telefon', 'Phone', 'Tel', 'Phone_Billing'],
        'Adresa_originala': ['Adresa', 'Adresa_originala', 'Address', 'Adresă', 'Full Address']
    }
    
    for system_col, user_options in mapping.items():
        if system_col not in df.columns:
            for option in user_options:
                if option in df.columns:
                    df[system_col] = df[option]
                    break
            if system_col not in df.columns:
                df[system_col] = ""
                
    return df, original_cols

# --- Core Routing Algorithm ---
def generate_optimized_routes(orders_df, original_columns):
    # Generăm automat 3 curieri impliciți pentru a simplifica procesul dispecerului
    couriers_data = {
        'Curier_ID': ['C01', 'C02', 'C03'],
        'Nume_curier': ['Curier Principal 1', 'Curier Principal 2', 'Curier Principal 3'],
        'Capacitate_max_livrari': [20, 20, 20]
    }
    active_couriers = pd.DataFrame(couriers_data)

    # Coordonate implicite de start (Centrul Bucureștiului - Piața Unirii)
    c_coords = {
        'C01': {'start_lat': 44.4261, 'start_lon': 26.1024, 'end_lat': 44.4261, 'end_lon': 26.1024},
        'C02': {'start_lat': 44.4325, 'start_lon': 26.1001, 'end_lat': 44.4325, 'end_lon': 26.1001},
        'C03': {'start_lat': 44.4011, 'start_lon': 26.1189, 'end_lat': 44.4011, 'end_lon': 26.1189}
    }

    orders = orders_df.copy()
    for col in ['Curier', 'Secventa', 'Ora_estimata_sosire', 'Slot_fix_livrare', 'Regula_slot_aplicata', 'Link_navigatie', 'Status']:
        if col not in orders.columns:
            orders[col] = ""

    courier_tracks = {c_id: [] for c_id in active_couriers['Curier_ID']}
    courier_counts = {c_id: 0 for c_id in active_couriers['Curier_ID']}
    
    # Împărțim în comenzi care au coordonate valide din KML și cele care nu au
    routable_items = orders[orders['Latitudine'].notna() & orders['Longitudine'].notna()].to_dict('records')
    unroutable = orders[orders['Latitudine'].isna() | orders['Longitudine'].isna()].copy()
    
    if len(routable_items) == 0:
        return None, "Nicio comandă din Excel nu s-a putut potrivi cu punctele din My Maps. Verificați dacă ID-urile coincid."

    while len(routable_items) > 0:
        best_score = float('inf')
        best_cou
