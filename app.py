import streamlit as st
import pandas as pd
import numpy as np
import math
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import io

# --- Page Configuration ---
st.set_page_config(page_title="RoRoute - Planificator My Maps", layout="wide")

# --- Funcție de extragere a datelor exacte din fișierul KML (Google My Maps) ---
def parse_kml_to_dataframe(kml_file):
    """Extrage numele, adresa și coordonatele exacte din fișierul exportat din My Maps."""
    try:
        kml_content = kml_file.read()
        # Definim namespace-ul standard pentru KML
        namespaces = {'kml': 'http://www.opengis.net/kml/2.2'}
        root = ET.fromstring(kml_content)
        
        records = []
        # Căutăm toate punctele (Placemark) din fișier
        for placemark in root.findall('.//kml:Placemark', namespaces):
            name = placemark.find('kml:name', namespaces)
            name_text = name.text if name is not None else "Fără Nume"
            
            description = placemark.find('kml:description', namespaces)
            desc_text = description.text if description is not None else ""
            
            coordinates = placemark.find('.//kml:coordinates', namespaces)
            if coordinates is not None and coordinates.text:
                coords_str = coordinates.text.strip()
                # Formatul KML este: longitudine,latitudine,altitudine
                parts = coords_str.split(',')
                if len(parts) >= 2:
                    lon = float(parts[0].strip())
                    lat = float(parts[1].strip())
                    
                    records.append({
                        'Nr. Comanda': name_text,
                        'Adresa_originala': desc_text if desc_text else name_text,
                        'Latitudine': lat,
                        'Longitudine': lon,
                        'Status': 'Poziție Exactă (My Maps)'
                    })
                    
        if len(records) > 0:
            return pd.DataFrame(records), None
        else:
            return None, "Fișierul KML a fost citit, dar nu s-au găsit puncte geografice (Placemarks)."
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

# --- Sample Data Generator ---
def get_sample_data():
    orders_data = {
        'Nr. Comanda': [f"ORD-{i:03d}" for i in range(1, 6)],
        'First Name (Shipping)': ['Ion', 'Maria', 'Dan', 'Grigore', 'Oana'],
        'Last Name (Shipping)': ['Popescu', 'Ionescu', 'Vasile', 'Elena', 'Gheltu'],
        'Phone (Billing)': ['0722111222', '0733222333', '0744333444', '0786440547', '0720015842'],
        'Adresa': ['Bulevardul Unirii 10, Bucuresti', 'Strada Lipscani 22, Bucuresti', 'Soseaua Oltenitei 40, Bucuresti', 'Calea Mosilor 112, Bucuresti', 'Strada Lanariei 126, Bucuresti'],
        'Latitudine': [44.4261, 44.4325, 44.4011, 44.4389, 44.4172],
        'Longitudine': [26.1024, 26.1001, 26.1189, 26.1122, 26.1031],
        'Status': ['Coordonate Demo'] * 5
    }
    couriers_data = {
        'Curier_ID': ['C01', 'C02'],
        'Nume_curier': ['Alex Curier', 'Mihai Transport'],
        'Activ': [True, True],
        'Punct_plecare': ['Piata Unirii, Bucuresti', 'Piata Victoriei, Bucuresti'],
        'Punct_finalizare': ['Piata Unirii, Bucuresti', 'Piata Victoriei, Bucuresti'],
        'Capacitate_max_livrari': [20, 20]
    }
    return pd.DataFrame(orders_data), pd.DataFrame(couriers_data)

# --- Standardizer ---
def standardize_couriers_df(df):
    df = df.copy()
    if 'Curier_ID' not in df.columns: df['Curier_ID'] = [f"C{i}" for i in range(1, len(df)+1)]
    if 'Nume_curier' not in df.columns: df['Nume_curier'] = df['Curier_ID']
    if 'Activ' not in df.columns: df['Activ'] = True
    if 'Capacitate_max_livrari' not in df.columns: df['Capacitate_max_livrari'] = 20
    df['Activ'] = df['Activ'].apply(lambda x: str(x).strip().lower() in ['true', '1', 'da', 'yes', 'active'])
    return df

# --- Core Routing Algorithm ---
def generate_optimized_routes(orders_df, df_couriers):
    couriers = standardize_couriers_df(df_couriers)
    active_couriers = couriers[couriers['Activ'] == True].copy()
    
    if len(active_couriers) == 0:
        return None, "Nu există curieri activi în sistem."
    
    # Coordonate implicite pentru punctele de start curieri (Centrul Bucureștiului)
    c_coords = {}
    for idx, row in active_couriers.iterrows():
        c_coords[row['Curier_ID']] = {
            'start_lat': 44.4325, 'start_lon': 26.1001,
            'end_lat': 44.4325, 'end_lon': 26.1001
        }

    # Pregătire structură tabel final
    orders = orders_df.copy()
    for col in ['Curier', 'Secventa', 'Ora_estimata_sosire', 'Slot_fix_livrare', 'Regula_slot_aplicata', 'Link_navigatie']:
        orders[col] = ""

    courier_tracks = {c_id: [] for c_id in active_couriers['Curier_ID']}
    courier_counts = {c_id: 0 for c_id in active_couriers['Curier_ID']}
    
    unassigned_orders = orders.to_dict('records')
    
    while len(unassigned_orders) > 0:
        best_score = float('inf')
        best_courier = None
        best_order_idx = None
        
        for idx, ord_item in enumerate(unassigned_orders):
            for _, c_row in active_couriers.iterrows():
                c_id = c_row['Curier_ID']
                max_capacity = int(c_row.get('Capacitate_max_livrari', 20))
                
                if courier_counts[c_id] >= min(max_capacity, 20):
                    continue
                    
                c_loc = c_coords[c_id]
                dist_from_start = haversine_distance(ord_item['Latitudine'], ord_item['Longitudine'], c_loc['start_lat'], c_loc['start_lon'])
                dist_to_finish = haversine_distance(ord_item['Latitudine'], ord_item['Longitudine'], c_loc['end_lat'], c_loc['end_lon'])
                
                if len(courier_tracks[c_id]) > 0:
                    last_stop = courier_tracks[c_id][-1]
                    dist_to_last_stop = haversine_distance(ord_item['Latitudine'], ord_item['Longitudine'], last_stop['Latitudine'], last_stop['Longitudine'])
                else:
                    dist_to_last_stop = dist_from_start
                
                load_penalty = courier_counts[c_id] * 2.5
                score = (dist_from_start * 0.3) + (dist_to_finish * 0.2) + (dist_to_last_stop * 0.5) + load_penalty
                
                if score < best_score:
                    best_score = score
                    best_courier = c_id
                    best_order_idx = idx
                    
        if best_courier is None:
            break
            
        chosen_order = unassigned_orders.pop(best_order_idx)
        chosen_order['Curier_alocat'] = best_courier
        courier_tracks[best_courier].append(chosen_order)
        courier_counts[best_courier] += 1

    final_route_records = []
    
    for _, c_row in active_couriers.iterrows():
        c_id = c_row['Curier_ID']
        track = courier_tracks[c_id]
        if not track:
            continue
            
        sequenced_track = []
        curr_lat = c_coords[c_id]['start_lat']
        curr_lon = c_coords[c_id]['start_lon']
        
        while len(track) > 0:
            next_idx = min(range(len(track)), key=lambda i: haversine_distance(curr_lat, curr_lon, track[i]['Latitudine'], track[i]['Longitudine']))
            next_stop = track.pop(next_idx)
            sequenced_track.append(next_stop)
            curr_lat = next_stop['Latitudine']
            curr_lon = next_stop['Longitudine']

        current_time = datetime.strptime("10:00", "%H:%M")
        windows = [
            (datetime.strptime("10:00", "%H:%M"), datetime.strptime("12:00", "%H:%M"), "10:00-12:00"),
            (datetime.strptime("12:00", "%H:%M"), datetime.strptime("14:00", "%H:%M"), "12:00-14:00"),
            (datetime.strptime("14:00", "%H:%M"), datetime.strptime("16:00", "%H:%M"), "14:00-16:00"),
            (datetime.strptime("16:00", "%H:%M"), datetime.strptime("18:00", "%H:%M"), "16:00-18:00"),
            (datetime.strptime("18:00", "%H:%M"), datetime.strptime("20:00", "%H:%M"), "18:00-20:00")
        ]
        current_window_idx = 0
        
        for seq, stop in enumerate(sequenced_track, start=1):
            if seq == 1:
                prev_lat, prev_lon = c_coords[c_id]['start_lat'], c_coords[c_id]['start_lon']
            else:
                prev_lat, prev_lon = sequenced_track[seq-2]['Latitudine'], sequenced_track[seq-2]['Longitudine']
                
            dist = haversine_distance(prev_lat, prev_lon, stop['Latitudine'], stop['Longitudine'])
            travel_time_min = (dist / 30.0) * 60.0
            
            current_time += timedelta(minutes=travel_time_min)
            arrival_time_str = current_time.strftime("%H:%M")
            
            while current_window_idx < len(windows) and current_time > windows[current_window_idx][1]:
                current_window_idx += 1
                
            if current_window_idx >= len(windows):
                applied_slot = "După 20:00"
            else:
                applied_slot = windows[current_window_idx][2]
            
            stop['Curier'] = c_row['Nume_curier']
            stop['Secventa'] = seq
            stop['Ora_estimata_sosire'] = arrival_time_str
            stop['Slot_fix_livrare'] = applied_slot
            stop['Regula_slot_aplicata'] = "Păstrat în primul slot" if seq <= 2 else "Alocat dinamic pe bază ETA"
            stop['Link_navigatie'] = f"http://maps.google.com/maps?q={stop['Latitudine']},{stop['Longitudine']}"
            
            final_route_records.append(stop)
            current_time += timedelta(minutes=20) # 10 min stop + 10 min buffer

    df_final = pd.DataFrame(final_route_records) if final_route_records else pd.DataFrame()
    return df_final, None

# --- UI Interface ---
st.title("🚚 RoRoute - Planificator cu Import direct din Google My Maps")
st.subheader("Folosește poziționările tale perfecte din hărți")

mode = st.sidebar.radio("Sursă Date Adrese", ["Încarcă fișier KML din My Maps", "Mod Demo (Date Test)"])

orders_df, couriers_df = None, None

if mode == "Mod Demo (Date Test)":
    orders_df, couriers_df = get_sample_data()
else:
    st.sidebar.markdown("### 1. Încarcă Harta de adrese (.kml)")
    uploaded_kml = st.sidebar.file_uploader("Încarcă fișierul descărcat din My Maps", type=["kml"])
    
    if uploaded_kml:
        parsed_df, err = parse_kml_to_dataframe(uploaded_kml)
        if err:
            st.sidebar.error(err)
        else:
            orders_df = parsed_df
            st.sidebar.success(f"✅ S-au încărcat {len(orders_df)} adrese din Google My Maps!")
            
    # Configurație automată curieri simplă
    couriers_df = pd.DataFrame({
        'Curier_ID': ['C01', 'C02', 'C03'],
        'Nume_curier': ['Curier Traseu 1', 'Curier Traseu 2', 'Curier Traseu 3'],
        'Activ': [True, True, True]
    })

if orders_df is not None:
    st.markdown("### 📋 Adrese active preluate cu coordonate exacte")
    st.dataframe(orders_df, use_container_width=True)
    
    if st.button("🚀 Optimizează Traseele pe Baza Hărții", type="primary"):
        routes_res, _ = generate_optimized_routes(orders_df, couriers_df)
        
        if routes_res is not None and not routes_res.empty:
            st.success("✅ Traseele au fost calculate folosind punctele exacte!")
            
            st.markdown("### 🗺️ Vizualizare Trasee Optimizate")
            st.map(routes_res[['Latitudine', 'Longitudine']].rename(columns={'Latitudine': 'latitude', 'Longitudine': 'longitude'}))
            
            st.markdown("### 🗺️ Tabel Trasee Finale")
            st.dataframe(routes_res.sort_values(by=['Curier', 'Secventa']), use_container_width=True)
            
            csv_buffer = io.StringIO()
            routes_res.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
            st.download_button(
                label="📥 Descarcă Fișier Trasee (Format CSV)",
                data=csv_buffer.getvalue(),
                file_name="Rute_Perfecte_MyMaps.csv",
                mime="text/csv"
            )
else:
    st.info("💡 Exportă harta din My Maps ca fișier .kml și încarcă-l în meniul din stânga pentru a rula aplicația cu precizie chirurgicală.")
