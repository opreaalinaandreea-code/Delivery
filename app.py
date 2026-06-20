import streamlit as st
import pandas as pd
import numpy as np
import math
from datetime import datetime, timedelta
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
import io

# --- Page Configuration ---
st.set_page_config(page_title="RoRoute - Planificator Automat Trasee", layout="wide")

# --- Simple Local Cache For Geocoding ---
if 'geocoding_cache' not in st.session_state:
    st.session_state.geocoding_cache = {}

# --- Geocoding Service Function ---
def geocode_address(address, localitate="", judet=""):
    """Geocodes an address reliably with caching and Romanian fallbacks."""
    if not address or pd.isna(address):
        return None, None, "Adresă Lipsă"
        
    full_query = f"{address}"
    if localitate and not pd.isna(localitate): full_query += f", {localitate}"
    if judet and not pd.isna(judet): full_query += f", {judet}"
    full_query += ", Romania"
    
    if full_query in st.session_state.geocoding_cache:
        return st.session_state.geocoding_cache[full_query]
        
    geolocator = Nominatim(user_agent="roroute_planner_v1_operational_prod")
    try:
        location = geolocator.geocode(full_query, timeout=4)
        if location:
            res = (location.latitude, location.longitude, location.address)
            st.session_state.geocoding_cache[full_query] = res
            return res
        
        # Fallback to locality if specific address fails
        if localitate and not pd.isna(localitate):
            fallback = f"{localitate}, Romania"
            location = geolocator.geocode(fallback, timeout=4)
            if location:
                res = (location.latitude, location.longitude, f"FALLBACK LOC: {location.address}")
                st.session_state.geocoding_cache[full_query] = res
                return res
    except (GeocoderTimedOut, GeocoderServiceError):
        pass
        
    return None, None, "Geocoding Eșuat / Necesită Revizie"

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
        'ID_Livrare': [f"ORD-{i:03d}" for i in range(1, 6)],
        'Client': ['Popescu Ion', 'Ionescu Maria', 'Vasile Dan', 'Elena Grigore', 'Oana Gheltu'],
        'Telefon': ['0722111222', '0733222333', '0744333444', '0786440547', '0720015842'],
        'Adresa_originala': ['Bulevardul Unirii 10', 'Strada Lipscani 22', 'Soseaua Oltenitei 40', 'Calea Mosilor 112', 'Strada Lanariei 126'],
        'Localitate_presupusa': ['Bucuresti', 'Bucuresti', 'Bucuresti', 'Bucuresti', 'Bucuresti'],
        'Judet': ['Bucuresti', 'Bucuresti', 'Bucuresti', 'Bucuresti', 'Bucuresti'],
        'Latitudine': [44.4261, 44.4325, 44.4011, 44.4389, 44.4172],
        'Longitudine': [26.1024, 26.1001, 26.1189, 26.1122, 26.1031],
        'Durata_stop_min': [10] * 5,
        'Timp_buffer_min': [10] * 5
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

# --- Standardizer / Column Mapper ---
def standardize_orders_df(df):
    """Maps custom user columns to required system terms flexibly."""
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    
    mapping = {
        'ID_Livrare': ['ID_Livrare', 'Nr. Comanda', 'Id', 'ID', 'Cod'],
        'Client': ['Client', 'Nume', 'First Name (Shipping)', 'Last Name (Shipping)', 'Name', 'Destinatar'],
        'Telefon': ['Telefon', 'Phone (Billing)', 'Phone', 'Tel'],
        'Adresa_originala': ['Adresa_originala', 'Adresa', 'Address', 'Adresă'],
        'Localitate_presupusa': ['Localitate_presupusa', 'Localitate', 'Oras', 'Oraș', 'City'],
        'Judet': ['Judet', 'Județ', 'County']
    }
    
    for system_col, user_options in mapping.items():
        if system_col not in df.columns:
            for option in user_options:
                if option in df.columns:
                    df[system_col] = df[option]
                    break
            if system_col not in df.columns:
                df[system_col] = ""
                
    if 'Durata_stop_min' not in df.columns: df['Durata_stop_min'] = 10
    if 'Timp_buffer_min' not in df.columns: df['Timp_buffer_min'] = 10
    return df

def standardize_couriers_df(df):
    """Maps courier files securely or creates a dummy if columns/files are partial."""
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    
    mapping = {
        'Curier_ID': ['Curier_ID', 'ID', 'Id', 'Cod'],
        'Nume_curier': ['Nume_curier', 'Curier', 'Nume', 'Name'],
        'Activ': ['Activ', 'Active', 'Status'],
        'Punct_plecare': ['Punct_plecare', 'Plecare', 'Start'],
        'Punct_finalizare': ['Punct_finalizare', 'Sosire', 'Final', 'End'],
        'Capacitate_max_livrari': ['Capacitate_max_livrari', 'Capacitate', 'Max']
    }
    
    for system_col, user_options in mapping.items():
        if system_col not in df.columns:
            for option in user_options:
                if option in df.columns:
                    df[system_col] = df[option]
                    break
    
    if 'Curier_ID' not in df.columns: df['Curier_ID'] = [f"C{i}" for i in range(1, len(df)+1)]
    if 'Nume_curier' not in df.columns: df['Nume_curier'] = df['Curier_ID']
    if 'Activ' not in df.columns: df['Activ'] = True
    if 'Punct_plecare' not in df.columns: df['Punct_plecare'] = "Bucuresti, Romania"
    if 'Punct_finalizare' not in df.columns: df['Punct_finalizare'] = "Bucuresti, Romania"
    if 'Capacitate_max_livrari' not in df.columns: df['Capacitate_max_livrari'] = 20
    
    df['Activ'] = df['Activ'].apply(lambda x: str(x).strip().lower() in ['true', '1', 'da', 'yes', 'active'])
    return df

# --- Core Routing Algorithm ---
def generate_optimized_routes(df_orders, df_couriers):
    orders = standardize_orders_df(df_orders)
    couriers = standardize_couriers_df(df_couriers)
    
    active_couriers = couriers[couriers['Activ'] == True].copy()
    if len(active_couriers) == 0:
        return None, "Nu există curieri activi în fișier. Vă rugăm bifați/setați cel puțin un curier ca Activ."
        
    if len(active_couriers) > 4:
        active_couriers = active_couriers.head(4)

    c_coords = {}
    for idx, row in active_couriers.iterrows():
        lat_s, lon_s, _ = geocode_address(row['Punct_plecare'])
        lat_f, lon_f, _ = geocode_address(row['Punct_finalizare'])
        c_coords[row['Curier_ID']] = {
            'start_lat': lat_s or 44.4325, 'start_lon': lon_s or 26.1001,
            'end_lat': lat_f or 44.4325, 'end_lon': lon_f or 26.1001
        }

    # FIX: Initialize columns explicitly forcing Object/String types to avoid strict Pandas 3.14 dtype validation crashes
    for col in ['Latitudine', 'Longitudine']:
        if col not in orders.columns:
            orders[col] = np.nan
            
    for col in ['Geocoded_address', 'Status', 'Curier_alocat']:
        if col not in orders.columns:
            orders[col] = ""
            orders[col] = orders[col].astype(object)

    with st.spinner("Geocodare adrese în desfășurare..."):
        for idx, row in orders.iterrows():
            if pd.isna(row['Latitudine']) or pd.isna(row['Longitudine']) or row['Latitudine'] == "":
                lat, lon, geo_addr = geocode_address(row['Adresa_originala'], row.get('Localitate_presupusa', ''), row.get('Judet', ''))
                orders.at[idx, 'Latitudine'] = lat
                orders.at[idx, 'Longitudine'] = lon
                orders.at[idx, 'Geocoded_address'] = str(geo_addr)
                orders.at[idx, 'Status'] = 'Geocodat Automat' if lat else 'Necesită Revizie Manuală'
            else:
                orders.at[idx, 'Status'] = 'Coordonate Existente'
                if pd.isna(row['Geocoded_address']) or row['Geocoded_address'] == "":
                    orders.at[idx, 'Geocoded_address'] = str(row['Adresa_originala'])

    unroutable = orders[orders['Latitudine'].isna() | orders['Longitudine'].isna()].copy()
    routable = orders.dropna(subset=['Latitudine', 'Longitudine']).copy()
    
    courier_tracks = {c_id: [] for c_id in active_couriers['Curier_ID']}
    courier_counts = {c_id: 0 for c_id in active_couriers['Curier_ID']}
    
    unassigned_orders = routable.to_dict('records')
    
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

    for left_item in unassigned_orders:
        left_item['Status'] = 'Nefinalizat - Lipsă Capacitate'
        left_item['Curier_alocat'] = 'Neatribuit'
        unroutable = pd.concat([unroutable, pd.DataFrame([left_item])], ignore_index=True)

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
                rule_desc = "Depășire program"
            else:
                applied_slot = windows[current_window_idx][2]
                rule_desc = "Păstrat în primul slot conform regulament" if seq <= 2 else "Alocat dinamic pe bază ETA"
            
            stop['Curier'] = c_row['Nume_curier']
            stop['Secventa'] = seq
            stop['Ora_estimata_sosire'] = arrival_time_str
            stop['Slot_fix_livrare'] = applied_slot
            stop['Regula_slot_aplicata'] = rule_desc
            stop['Link_navigatie'] = f"http://maps.google.com/?q={stop['Latitudine']},{stop['Longitudine']}"
            stop['Status'] = 'Optimizat'
            
            final_route_records.append(stop)
            
            stop_duration = int(stop.get('Durata_stop_min', 10))
            buffer_duration = int(stop.get('Timp_buffer_min', 10))
            current_time += timedelta(minutes=stop_duration + buffer_duration)

    df_routes_out = pd.DataFrame(final_route_records) if final_route_records else pd.DataFrame()
    return df_routes_out, unroutable

# --- UI Layout Interface ---
st.title("🚚 RoRoute - Planificator Automat de Trasee")
st.subheader("Sistem Operațional Centralizat pentru Dispecerat")

mode = st.sidebar.radio("Sursă Date", ["Mod Demo (Date Test)", "Încarcă Fişiere Proprii"])

orders_df, couriers_df = None, None

if mode == "Mod Demo (Date Test)":
    st.sidebar.info("Rulează aplicația folosind adrese preconfigurate demo.")
    orders_df, couriers_df = get_sample_data()
else:
    st.sidebar.markdown("### Încarcă Documente (.csv, .xlsx)")
    uploaded_orders = st.sidebar.file_uploader("Tabel Comenzi / Livrări", type=["csv", "xlsx"])
    uploaded_couriers = st.sidebar.file_uploader("Tabel Configurație Curieri", type=["csv", "xlsx"])
    
    if uploaded_orders:
        if uploaded_orders.name.endswith('.csv'):
            orders_df = pd.read_csv(uploaded_orders)
        else:
            orders_df = pd.read_excel(uploaded_orders)
            
    if uploaded_couriers:
        if uploaded_couriers.name.endswith('.csv'):
            couriers_df = pd.read_csv(uploaded_couriers)
        else:
            couriers_df = pd.read_excel(uploaded_couriers)
    elif uploaded_orders is not None:
        st.sidebar.warning("⚠️ Fișier curieri lipsă. Generăm automat 2 curieri impliciti.")
        couriers_df = pd.DataFrame({
            'Curier_ID': ['C01', 'C02'],
            'Nume_curier': ['Curier Principal 1', 'Curier Principal 2'],
            'Activ': [True, True]
        })

if orders_df is not None and couriers_df is not None:
    tab_ord, tab_cour = st.tabs(["📋 Vizualizare Date Încărcate", "🛵 Configurație Curieri"])
    with tab_ord:
        st.dataframe(orders_df, use_container_width=True)
    with tab_cour:
        st.dataframe(couriers_df, use_container_width=True)
        
    if st.button("🚀 Generează și Optimizează Traseele", type="primary"):
        routes_res, unrouted_res = generate_optimized_routes(orders_df, couriers_df)
        
        if routes_res is not None and not routes_res.empty:
            st.success("✅ Optimizare Finalizată cu Succes!")
            
            kpi_cols = st.columns(4)
            total_allocated = len(routes_res)
            unique_couriers = routes_res['Curier'].nunique()
            avg_stops = round(total_allocated / unique_couriers, 1) if unique_couriers > 0 else 0
            
            kpi_cols[0].metric("Total Livrări Alocate", total_allocated)
            kpi_cols[1].metric("Curieri Activi pe Traseu", unique_couriers)
            kpi_cols[2].metric("Medie Livrări / Curier", avg_stops)
            kpi_cols[3].metric("Comenzi Eșuate", len(unrouted_res) if unrouted_res is not None else 0)
            
            st.markdown("#### ⚖️ Rezumat Trasee Curieri")
            balance_summary = []
            for c_name, group in routes_res.groupby('Curier'):
                balance_summary.append({
                    'Curier': c_name,
                    'Număr Comenzi': len(group),
                    'Prima Livrare': group['Ora_estimata_sosire'].min(),
                    'Ultima Livrare': group['Ora_estimata_sosire'].max(),
                    'Sloturi Acoperite': ", ".join(group['Slot_fix_livrare'].unique())
                })
            st.table(pd.DataFrame(balance_summary))
            
            st.markdown("### 🗺️ Ordinea Traseelor Detaliată")
            display_cols = ['Curier', 'Secventa', 'ID_Livrare', 'Client', 'Telefon', 
                            'Adresa_originala', 'Localitate_presupusa', 'Judet', 
                            'Ora_estimata_sosire', 'Slot_fix_livrare', 'Regula_slot_aplicata', 'Link_navigatie']
            valid_display_cols = [c for c in display_cols if c in routes_res.columns]
            st.dataframe(routes_res[valid_display_cols].sort_values(by=['Curier', 'Secventa']), use_container_width=True)
            
            csv_buffer = io.StringIO()
            routes_res[valid_display_cols].to_csv(csv_buffer, index=False, encoding='utf-8-sig')
            st.download_button(
                label="📥 Descarcă Fișier Trasee (Format CSV)",
                data=csv_buffer.getvalue(),
                file_name=f"Rute_Planificate_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )
        else:
            st.error(routes_res if routes_res else "Eroare necunoscută la generare.")
else:
    st.info("💡 Vă rugăm să selectați un mod din stânga pentru a începe.")
