import streamlit as st
import pandas as pd
import numpy as np
import math
import re
from datetime import datetime, timedelta
from geopy.geocoders import Nominatim
import io

# --- Page Configuration ---
st.set_page_config(page_title="RoRoute - Planificator Automat Trasee", layout="wide")

if 'geocoding_cache' not in st.session_state:
    st.session_state.geocoding_cache = {}

def clean_romanian_address(address_text):
    if not address_text or pd.isna(address_text):
        return ""
    addr = str(address_text).lower().strip()
    addr = re.sub(r'\bbl\b|\bbloc\b.*', '', addr)
    addr = re.sub(r'\bsc\b|\bscara\b.*', '', addr)
    addr = re.sub(r'\bap\b|\bapartament\b.*', '', addr)
    addr = re.sub(r'\bet\b|\betaj\b.*', '', addr)
    addr = re.sub(r'\binterfon\b.*', '', addr)
    addr = re.sub(r'\bsos\b|\bşos\b|\bsoseaua\b', 'soseaual', addr)
    addr = re.sub(r'\bstr\b|\bstrada\b', 'strada', addr)
    addr = re.sub(r'\bbd\b|\bblv\b|\bbvd\b|\bbulevardul\b', 'bulevardul', addr)
    addr = re.sub(r'\bcal\b|\bcalea\b', 'calea', addr)
    addr = re.sub(r'\bint\b|\bintrarea\b', 'intrarea', addr)
    addr = re.sub(r'\bprel\b|\bprelungirea\b', 'prelungirea', addr)
    addr = re.sub(r'(\d+)-\d+', r'\1', addr)
    addr = addr.replace('ş', 's').replace('ţ', 't').replace('ă', 'a').replace('î', 'i').replace('â', 'a')
    return addr.strip().title()

def extract_locality_fallback(address_text):
    if not address_text or pd.isna(address_text):
        return "Bucuresti"
    parts = str(address_text).split(',')
    if len(parts) > 0:
        loc = parts[0].strip().title()
        return loc if len(loc) > 2 else "Bucuresti"
    return "Bucuresti"

def geocode_address_bulletproof(address_raw):
    if not address_raw or pd.isna(address_raw):
        return 44.4325, 26.1001, "Adresă Lipsă - Centru Hub", "Punct Default"
    addr_str = str(address_raw).strip()
    if addr_str in st.session_state.geocoding_cache:
        return st.session_state.geocoding_cache[addr_str]
        
    clean_addr = clean_romanian_address(addr_str)
    query_full = clean_addr if "romania" in clean_addr.lower() else f"{clean_addr}, Romania"
    geolocator = Nominatim(user_agent="roroute_planner_free_final_v6_timefixed")
    
    try:
        location = geolocator.geocode(query_full, timeout=5)
        if location:
            res = (location.latitude, location.longitude, location.address, "Geocodat Complet")
            st.session_state.geocoding_cache[addr_str] = res
            return res
    except Exception:
        pass
        
    locality = extract_locality_fallback(addr_str)
    query_loc = f"{locality}, Romania"
    try:
        location = geolocator.geocode(query_loc, timeout=4)
        if location:
            res = (location.latitude, location.longitude, f"Aproximat în: {location.address}", "Aproximat Localitate")
            st.session_state.geocoding_cache[addr_str] = res
            return res
    except Exception:
        pass
        
    res = (44.4325, 26.1001, "Localizare eșuată - Plasat la Hub Central", "Necesită Atenție Curier")
    st.session_state.geocoding_cache[addr_str] = res
    return res

def haversine_distance(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2) or any(math.isnan(x) for x in (lat1, lon1, lat2, lon2)):
        return 999.0
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(delta_lambda/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1-a))

def standardize_orders_df(df):
    df = df.copy()
    original_cols = list(df.columns)
    df.columns = [str(c).strip() for c in df.columns]
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

def generate_optimized_routes(orders_df, original_columns):
    couriers_data = {
        'Curier_ID': ['C01', 'C02', 'C03'],
        'Nume_curier': ['Curier Principal 1', 'Curier Principal 2', 'Curier Principal 3'],
        'Capacitate_max_livrari': [20, 20, 20]
    }
    active_couriers = pd.DataFrame(couriers_data)
    
    c_coords = {
        'C01': {'start_lat': 44.4261, 'start_lon': 26.1024, 'end_lat': 44.4261, 'end_lon': 26.1024},
        'C02': {'start_lat': 44.4325, 'start_lon': 26.1001, 'end_lat': 44.4325, 'end_lon': 26.1001},
        'C03': {'start_lat': 44.4011, 'start_lon': 26.1189, 'end_lat': 44.4011, 'end_lon': 26.1189}
    }

    orders = orders_df.copy()
    for col in ['Curier', 'Secventa', 'Ora_estimata_sosire', 'Slot_fix_livrare', 'Regula_slot_aplicata', 'Link_navigatie', 'Status']:
        orders[col] = ""
        orders[col] = orders[col].astype(object)

    with st.spinner("Localizare adrese prin algoritmul de curățare românesc..."):
        for idx, row in orders.iterrows():
            lat, lon, geo_addr, id_type = geocode_address_bulletproof(row['Adresa_originala'])
            orders.at[idx, 'Latitudine'] = lat
            orders.at[idx, 'Longitudine'] = lon
            orders.at[idx, 'Geocoded_address'] = str(geo_addr)
            orders.at[idx, 'Status'] = id_type

    courier_tracks = {c_id: [] for c_id in active_couriers['Curier_ID']}
    courier_counts = {c_id: 0 for c_id in active_couriers['Curier_ID']}
    unassigned_orders = orders.to_dict('records')
    unroutable = pd.DataFrame(columns=orders.columns)
    
    while len(unassigned_orders) > 0:
        best_score = float('inf')
        best_courier = None
        best_order_idx = None
        
        for idx, ord_item in enumerate(unassigned_orders):
            for _, c_row in active_couriers.iterrows():
                c_id = c_row['Curier_ID']
                if courier_counts[c_id] >= int(c_row['Capacitate_max_livrari']):
                    continue
                c_loc = c_coords[c_id]
                
                dist_from_start = haversine_distance(ord_item['Latitudine'], ord_item['Longitudine'], c_loc['start_lat'], c_loc['start_lon'])
                dist_to_finish = haversine_distance(ord_item['Latitudine'], ord_item['Longitudine'], c_loc['end_lat'], c_loc['end_lon'])
                
                if len(courier_tracks[c_id]) > 0:
                    last_stop = courier_tracks[c_id][-1]
                    dist_to_last_stop = haversine_distance(ord_item['Latitudine'], ord_item['Longitudine'], last_stop['Latitudine'], last_stop['Longitudine'])
                else:
                    dist_to_last_stop = dist_from_start
                
                score = (dist_from_start * 0.3) + (dist_to_finish * 0.2) + (dist_to_last_stop * 0.5) + (courier_counts[c_id] * 2.5)
                
                # Linii scurte anti-decupare GitHub
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

    for left_item in unassigned_orders:
        left_item['Status'] = 'Nefinalizat - Capacitate Depășită'
        unroutable = pd.concat([unroutable, pd.DataFrame([left_item])], ignore_index=True)

    final_route_records = []
    for _, c_row in active_couriers.iterrows():
        c_id = c_row['Curier_ID']
        track = courier_tracks[c_id]
        if not track:
            continue
            
        sequenced_track = []
        curr_lat, curr_lon = c_coords[c_id]['start_lat'], c_coords[c_id]['start_lon']
        while len(track) > 0:
            next_idx = min(range(len(track)), key=lambda i: haversine_distance(curr_lat, curr_lon, track[i]['Latitudine'], track[i]['Longitudine']))
            next_stop = track.pop(next_idx)
            sequenced_track.append(next_stop)
            curr_lat, curr_lon = next_stop['Latitudine'], next_stop['Longitudine']

        current_time = datetime.strptime("09:30", "%H:%M")
        
        for seq, stop in enumerate(sequenced_track, start=1):
            if seq == 1:
                prev_lat, prev_lon = c_coords[c_id]['start_lat'], c_coords[c_id]['start_lon']
            else:
                prev_lat, prev_lon = sequenced_track[seq-2]['Latitudine'], sequenced_track[seq-2]['Longitudine']
                
            dist = haversine_distance(prev_lat, prev_lon, stop['Latitudine'], stop['Longitudine'])
            travel_time_min = (dist / 30.0) * 60.0
            
            current_time += timedelta(minutes=travel_time_min)
            arrival_time_str = current_time.strftime("%H:%M")
            
            rounded_hour = current_time.hour
            slot_start_str = f"{rounded_hour:02d}:00"
            slot_end_str = f"{(rounded_hour + 2):02d}:00"
            applied_slot = f"{slot_start_str}-{slot_end_str}"
            
            stop['Curier'] = c_row['Nume_curier']
            stop['Secventa'] = seq
            stop['Ora_estimata_sosire'] = arrival_time_str
            stop['Slot_fix_livrare'] = applied_slot
            stop['Regula_slot_aplicata'] = "Rotunjire în jos la oră fixă + Fereastră 2h"
            stop['Link_navigatie'] = f"http://maps.google.com/?q={stop['Latitudine']},{stop['Longitudine']}"
            
            final_route_records.append(stop)
            current_time += timedelta(minutes=20)

    df_final_output = pd.DataFrame(final_route_records) if final_route_records else pd.DataFrame()
    if not df_final_output.empty and not unroutable.empty:
        df_final_output = pd.concat([df_final_output, unroutable], ignore_index=True)
    elif df_final_output.empty:
        df_final_output = unroutable

    new_system_cols = ['Curier', 'Secventa', 'Ora_estimata_sosire', 'Slot_fix_livrare', 'Regula_slot_aplicata', 'Link_navigatie', 'Status', 'Latitudine', 'Longitudine', 'Geocoded_address']
    final_cols_order = original_columns + [c for c in new_system_cols if c not in original_columns]
    existing_cols_order = [c for c in final_cols_order if c in df_final_output.columns]
    
    review_needed = df_final_output[df_final_output['Status'].isin(['Aproximat Localitate', 'Necesită Atenție Curier'])]
    return df_final_output[existing_cols_order], review_needed

# --- UI Interface ---
st.title("🚚 RoRoute - Planificator Inteligent de Trasee")
st.subheader("Sistem complet automatizat cu sloturi dinamice calculate prin rotunjire")

uploaded_excel = st.file_uploader("Încarcă Tabelul Excel sau CSV cu Comenzi", type=["csv", "xlsx"])

if uploaded_excel:
    df_raw = pd.read_csv(uploaded_excel) if uploaded_excel.name.endswith('.csv') else pd.read_excel(uploaded_excel)
    orders_mapped, original_columns_list = standardize_orders_df(df_raw)
    st.success(f"📋 S-au citit cu succes {len(orders_mapped)} comenzi din fișier!")
    st.dataframe(df_raw, use_container_width=True)
    
    if st.button("🚀 Generează și Planifică Traseele Curierilor", type="primary"):
        routes_res, review_needed_df = generate_optimized_routes(orders_mapped, original_columns_list)
        
        if routes_res is not None and isinstance(routes_res, pd.DataFrame) and not routes_res.empty:
            st.success("✅ Toate comenzile au fost procesate și distribuite curierilor!")
            routes_only = routes_res[routes_res['Curier'] != ""]
            total_allocated = len(routes_only)
            
            kpi_cols = st.columns(4)
            kpi_cols[0].metric("Total Livrări Alocate", total_allocated)
            kpi_cols[1].metric("Curieri Activi", routes_only['Curier'].nunique() if total_allocated > 0 else 0)
            kpi_cols[2].metric("Medie Livrări / Curier", round(total_allocated / routes_only['Curier'].nunique(), 1) if total_allocated > 0 else 0)
            kpi_cols[3].metric("Adrese Necesită Atenție", len(review_needed_df))
            
            if total_allocated > 0:
                st.markdown("### 🗺️ Vizualizare Trasee pe Hartă Interactivă")
                map_df = routes_only[['Latitudine', 'Longitudine']].dropna().rename(columns={'Latitudine': 'latitude', 'Longitudine': 'longitude'})
                st.map(map_df)
                
                st.markdown("#### ⚖️ Rezumat Timpi de Finalizare per Curier")
                balance_summary = []
                for c_name, group in routes_only.groupby('Curier'):
                    balance_summary.append({
                        'Curier': c_name,
                        'Număr Comenzi': len(group),
                        'Prima Livrare (ETA)': group['Ora_estimata_sosire'].min(),
                        'Ultima Livrare (Ora Finish)': group['Ora_estimata_sosire'].max(),
                        'Sloturi Acoperite': ", ".join(group['Slot_fix_livrare'].astype(str).unique())
                    })
                st.table(pd.DataFrame(balance_summary))
            
            if not review_needed_df.empty:
                st.warning("⚠️ Adrese aproximative detected:")
                st.dataframe(review_needed_df[['ID_Livrare', 'Client', 'Adresa_originala', 'Status', 'Geocoded_address']], use_container_width=True)

            st.markdown("### 🗺️ Tabel Trasee Finale (Conține toate coloanele tale originale)")
            st.dataframe(routes_res.sort_values(by=['Curier', 'Secventa']), use_container_width=True)
            
            csv_buffer = io.StringIO()
            routes_res.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
            st.download_button(
                label="📥 Descarcă Fișier Excel/CSV Complet Trasee",
                data=csv_buffer.getvalue(),
                file_name=f"Trasee_Complete_RoRoute_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )
else:
    st.info("💡 Încarcă fișierul Excel primit de la clienți în câmpul de mai sus pentru a genera automat foile de parcurs.")
