import streamlit as st
import pandas as pd
import numpy as np
import math
from datetime import datetime, timedelta
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
import io

# --- Page Configuration ---
st.set_page_config(page_title="RoRoute - Courier Route Planner", layout="wide")

# --- Simple Local Cache For Geocoding ---
if 'geocoding_cache' not in st.session_state:
    st.session_state.geocoding_cache = {}

# --- Geocoding Service Function ---
def geocode_address(address, localitate, judet):
    """
    Geocodes an address reliably with caching, custom user-agent, 
    and fallback lookups specific to Romania.
    """
    # Create distinct query strings
    full_query = f"{address}, {localitate}, {judet}, Romania"
    fallback_query = f"{localitate}, {judet}, Romania"
    
    if full_query in st.session_state.geocoding_cache:
        return st.session_state.geocoding_cache[full_query]
        
    geolocator = Nominatim(user_agent="roroute_planner_v1_operational")
    
    try:
        # Try full address lookup
        location = geolocator.geocode(full_query, timeout=4)
        if location:
            res = (location.latitude, location.longitude, location.address)
            st.session_state.geocoding_cache[full_query] = res
            return res
        
        # Try fallback lookup (locality scale)
        location = geolocator.geocode(fallback_query, timeout=4)
        if location:
            res = (location.latitude, location.longitude, f"FALLBACK: {location.address}")
            st.session_state.geocoding_cache[full_query] = res
            return res
            
    except (GeocoderTimedOut, GeocoderServiceError):
        pass
        
    return None, None, "Geocoding Failed / Manual Review Required"

# --- Distance Calculation (Haversine formula) ---
def haversine_distance(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2) or any(math.isnan(x) for x in (lat1, lon1, lat2, lon2)):
        return 999.0  # High penalty for missing coordinates
    R = 6371.0 # Earth radius in km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(delta_lambda/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1-a))

# --- Sample Data Generator ---
def get_sample_data():
    orders_data = {
        'ID_Livrare': [f"ORD-{i:03d}" for i in range(1, 16)],
        'Client': ['Popescu Ion', 'Ionescu Maria', 'Vasile Dan', 'Elena Grigore', 'Oana Gheltu', 
                   'Angelica Andresei', 'Mihaela Neagu', 'Cristina Enache', 'Alexandra Tatar', 'Alina Donca',
                   'Cornelia Ionescu', 'Radu Mihai', 'Andrei Stoica', 'Simona Sandu', 'Marius Vlad'],
        'Telefon': ['0722111222', '0733222333', '0744333444', '0786440547', '0720015842',
                    '0721205873', '0729890700', '0766429757', '0735312582', '0766437823',
                    '0747211311', '0725999888', '0723111444', '0755888222', '0761333999'],
        'Adresa_originala': ['Bulevardul Unirii 10', 'Strada Lipscani 22', 'Soseaua Oltenitei 40', 'Calea Mosilor 112', 'Strada Lanariei 126',
                             'Strada Campului 14D', 'Strada Irina Stanescu 3', 'Strada Tulnici 2', 'Soseaua Berceni 24', 'Strada Fortului 91D',
                             'Bulevardul Magheru 5', 'Strada Stirbei Voda 40', 'Soseaua Pipera 4', 'Strada Apusului 12', 'Bulevardul Timisoara 15'],
        'Localitate_presupusa': ['Bucuresti', 'Bucuresti', 'Bucuresti', 'Bucuresti', 'Bucuresti',
                                 'Berceni', 'Bucuresti', 'Bucuresti', 'Bucuresti', 'Domnesti',
                                 'Bucuresti', 'Bucuresti', 'Voluntari', 'Bucuresti', 'Bucuresti'],
        'Judet': ['Bucuresti', 'Bucuresti', 'Bucuresti', 'Bucuresti', 'Bucuresti',
                  'Ilfov', 'Bucuresti', 'Bucuresti', 'Bucuresti', 'Ilfov',
                  'Bucuresti', 'Bucuresti', 'Ilfov', 'Bucuresti', 'Bucuresti'],
        'Latitudine': [44.4261, 44.4325, 44.4011, 44.4389, 44.4172, 44.3633, 44.4211, 44.3912, 44.3855, 44.3981, 44.4442, 44.4368, 44.4812, 44.4344, 44.4215],
        'Longitudine': [26.1024, 26.1001, 26.1189, 26.1122, 26.1031, 26.1855, 26.0911, 26.1245, 26.1311, 25.9234, 26.0975, 26.0855, 26.1433, 26.0122, 26.0355],
        'Detalii_livrare': ['Ap 3', 'Interfon 22', 'Bl 6a, Ap 139', '', 'Etaj 1', 'Casa', 'Sector 5', 'Bl 47', 'La poarta', 'Casă', '', 'Etaj 3', 'Cladirea Noua', '', 'Sef depozit'],
        'Durata_stop_min': [10] * 15,
        'Timp_buffer_min': [10] * 15,
        'Status_confirmare_client': ['Confirmat'] * 15,
        'Observatii': [''] * 15
    }
    
    couriers_data = {
        'Curier_ID': ['C01', 'C02', 'C03'],
        'Nume_curier': ['Alex Curier', 'Mihai Transport', 'Elena Rusu'],
        'Activ': [True, True, True],
        'Punct_plecare': ['Piata Unirii, Bucuresti', 'Piata Victoriei, Bucuresti', 'Piata Sudului, Bucuresti'],
        'Punct_finalizare': ['Piata Unirii, Bucuresti', 'Piata Victoriei, Bucuresti', 'Piata Sudului, Bucuresti'],
        'Ora_plecare': ['10:00', '10:00', '10:00'],
        'Capacitate_max_livrari': [20, 20, 20],
        'Primul_slot_disponibil': ['10:00-12:00', '10:00-12:00', '10:00-12:00'],
        'Ora_limita_finalizare': ['18:00', '18:00', '18:00'],
        'Zona_preferata': ['Centru', 'Nord', 'Sud'],
        'Telefon_curier': ['0711000111', '0722000222', '0733000333'],
        'Observatii': ['', '', '']
    }
    
    return pd.DataFrame(orders_data), pd.DataFrame(couriers_data)


# --- Core Routing Algorithm ---
def generate_optimized_routes(df_orders, df_couriers):
    # 1. Normalize Couriers
    couriers = df_couriers[df_couriers['Activ'] == True].copy()
    if len(couriers) == 0:
        return None, "Nu exista curieri activi configurati."
    if len(couriers) > 4:
        couriers = couriers.head(4) # Limit to maximum 4 couriers
        
    # Geocode Courier Hubs / Start & End Coordinates dynamically for processing
    c_coords = {}
    for idx, row in couriers.iterrows():
        lat_s, lon_s, _ = geocode_address(row['Punct_plecare'], "Bucuresti", "Bucuresti")
        lat_f, lon_f, _ = geocode_address(row['Punct_finalizare'], "Bucuresti", "Bucuresti")
        c_coords[row['Curier_ID']] = {
            'start_lat': lat_s or 44.4325, 'start_lon': lon_s or 26.1001,
            'end_lat': lat_f or 44.4325, 'end_lon': lon_f or 26.1001
        }

    # 2. Normalize and Geocode Orders
    orders = df_orders.copy()
    
    # Fill structural missing columns if any
    for col in ['Latitudine', 'Longitudine', 'Geocoded_address', 'Status', 'Curier_alocat']:
        if col not in orders.columns:
            orders[col] = np.nan

    # Dynamic Geocoding Loop
    with st.spinner("Se procesează geocodarea adreselor lipsă..."):
        for idx, row in orders.iterrows():
            if pd.isna(row['Latitudine']) or pd.isna(row['Longitudine']):
                lat, lon, geo_addr = geocode_address(row['Adresa_originala'], row['Localitate_presupusa'], row['Judet'])
                orders.at[idx, 'Latitudine'] = lat
                orders.at[idx, 'Longitudine'] = lon
                orders.at[idx, 'Geocoded_address'] = geo_addr
                if lat is None:
                    orders.at[idx, 'Status'] = 'Necesita Revizie Manuala'
                else:
                    orders.at[idx, 'Status'] = 'Geocodat Automat'
            else:
                orders.at[idx, 'Status'] = 'Coordonate Existente'
                if pd.isna(row['Geocoded_address']):
                    orders.at[idx, 'Geocoded_address'] = row['Adresa_originala']

    # Separate unroutable rows
    unroutable = orders[orders['Latitudine'].isna() | orders['Longitudine'].isna()].copy()
    routable = orders.dropna(subset=['Latitudine', 'Longitudine']).copy()
    
    # Initialize courier assignment tracks
    courier_tracks = {c_id: [] for c_id in couriers['Curier_ID']}
    courier_counts = {c_id: 0 for c_id in couriers['Curier_ID']}
    
    # 3. Heuristic / Greedy Dispatch Loop with load and geography corridor logic
    unassigned_orders = routable.to_dict('records')
    
    while len(unassigned_orders) > 0:
        best_score = float('inf')
        best_courier = None
        best_order_idx = None
        
        for idx, ord_item in enumerate(unassigned_orders):
            for _, c_row in couriers.iterrows():
                c_id = c_row['Curier_ID']
                
                # Check maximum delivery restriction capacity rule
                max_capacity = int(c_row.get('Capacitate_max_livrari', 20))
                if courier_counts[c_id] >= min(max_capacity, 20):
                    continue
                    
                # Geography corridor calculations
                c_loc = c_coords[c_id]
                dist_from_start = haversine_distance(ord_item['Latitudine'], ord_item['Longitudine'], c_loc['start_lat'], c_loc['start_lon'])
                dist_to_finish = haversine_distance(ord_item['Latitudine'], ord_item['Longitudine'], c_loc['end_lat'], c_loc['end_lon'])
                
                # Proximity to last stop in current route to keep geographical compactness
                if len(courier_tracks[c_id]) > 0:
                    last_stop = courier_tracks[c_id][-1]
                    dist_to_last_stop = haversine_distance(ord_item['Latitudine'], ord_item['Longitudine'], last_stop['Latitudine'], last_stop['Longitudine'])
                else:
                    dist_to_last_stop = dist_from_start
                
                # Balanced flexible penalties
                load_penalty = courier_counts[c_id] * 2.5 
                
                # Combined Score
                score = (dist_from_start * 0.3) + (dist_to_finish * 0.2) + (dist_to_last_stop * 0.5) + load_penalty
                
                if score < best_score:
                    best_score = score
                    best_courier = c_id
                    best_order_idx = idx
                    
        if best_courier is None:
            # Capacity cap reached or all available constraints saturated
            break
            
        # Execute strategic greedy placement
        chosen_order = unassigned_orders.pop(best_order_idx)
        chosen_order['Curier_alocat'] = best_courier
        courier_tracks[best_courier].append(chosen_order)
        courier_counts[best_courier] += 1

    # Put back any leftover orders if couriers filled completely up to their capacity ceiling
    for left_item in unassigned_orders:
        left_item['Status'] = 'Nefinalizat - Lipsa Capacitate Curier'
        left_item['Curier_alocat'] = 'Neatribuit'
        unroutable = pd.concat([unroutable, pd.DataFrame([left_item])], ignore_index=True)

    # 4. Route Routing Sequence Sequencing and Window ETA Management
    final_route_records = []
    
    for _, c_row in couriers.iterrows():
        c_id = c_row['Curier_ID']
        track = courier_tracks[c_id]
        if not track:
            continue
            
        # Sequence Route via standard Nearest Neighbor approach starting from Hub point
        sequenced_track = []
        curr_lat = c_coords[c_id]['start_lat']
        curr_lon = c_coords[c_id]['start_lon']
        
        while len(track) > 0:
            next_idx = min(range(len(track)), key=lambda i: haversine_distance(curr_lat, curr_lon, track[i]['Latitudine'], track[i]['Longitudine']))
            next_stop = track.pop(next_idx)
            sequenced_track.append(next_stop)
            curr_lat = next_stop['Latitudine']
            curr_lon = next_stop['Longitudine']

        # Time Window Window Estimation and Rule Allocation Mechanics
        # Shift configuration parameters initialization
        base_time = datetime.strptime("10:00", "%H:%M")
        current_time = base_time
        
        # Fixed Window Intervals configuration definition helper
        windows = [
            (datetime.strptime("10:00", "%H:%M"), datetime.strptime("12:00", "%H:%M"), "10:00-12:00"),
            (datetime.strptime("12:00", "%H:%M"), datetime.strptime("14:00", "%H:%M"), "12:00-14:00"),
            (datetime.strptime("14:00", "%H:%M"), datetime.strptime("16:00", "%H:%M"), "14:00-16:00"),
            (datetime.strptime("16:00", "%H:%M"), datetime.strptime("18:00", "%H:%M"), "16:00-18:00"),
            (datetime.strptime("18:00", "%H:%M"), datetime.strptime("20:00", "%H:%M"), "18:00-20:00")
        ]
        
        current_window_idx = 0
        
        for seq, stop in enumerate(sequenced_track, start=1):
            # Estimate driving time roughly mapped (Assume 40 km/h city average overhead plus traffic delays)
            if seq == 1:
                prev_lat, prev_lon = c_coords[c_id]['start_lat'], c_coords[c_id]['start_lon']
            else:
                prev_lat, prev_lon = sequenced_track[seq-2]['Latitudine'], sequenced_track[seq-2]['Longitudine']
                
            dist = haversine_distance(prev_lat, prev_lon, stop['Latitudine'], stop['Longitudine'])
            travel_time_min = (dist / 30.0) * 60.0 # 30km/h realistic delivery operational speed
            
            # Forward operational clocks 
            current_time += timedelta(minutes=travel_time_min)
            arrival_time_str = current_time.strftime("%H:%M")
            
            # Allocation inside Fixed slots according to explicit rules
            # Determine matching slot window bucket context
            while current_window_idx < len(windows) and current_time > windows[current_window_idx][1]:
                current_window_idx += 1
                
            if current_window_idx >= len(windows):
                applied_slot = "Dupa 20:00"
                rule_desc = "Depasire program standard"
            else:
                applied_slot = windows[current_window_idx][2]
                if seq <= 2:
                    rule_desc = "Pastrat in primul slot conform regulament"
                else:
                    rule_desc = "Alocat dinamic pe baza ETA curent"
            
            # Assemble operational data record
            stop['Curier'] = c_row['Nume_curier']
            stop['Secventa'] = seq
            stop['Ora_estimata_sosire'] = arrival_time_str
            stop['Slot_fix_livrare'] = applied_slot
            stop['Regula_slot_aplicata'] = rule_desc
            stop['Link_navigatie'] = f"https://www.google.com/maps/search/?api=1&query={stop['Latitudine']},{stop['Longitudine']}"
            stop['Status'] = 'Optimizat'
            
            final_route_records.append(stop)
            
            # Post stop process buffer duration accumulation
            stop_duration = int(stop.get('Durata_stop_min', 10))
            buffer_duration = int(stop.get('Timp_buffer_min', 10))
            current_time += timedelta(minutes=stop_duration + buffer_duration)

    df_routes_out = pd.DataFrame(final_route_records)
    return df_routes_out, unroutable

# --- UI Application Layout Interface ---
st.title("🚚 RoRoute - Planificator Automat de Trasee")
st.subheader("Sistem Operațional Centralizat pentru Dispecerat")

# Sidebar Configuration Control Room
st.sidebar.header("⚙️ Configurare Sistem")
mode = st.sidebar.radio("Sursă Date", ["Mod Demo (Date Test)", "Încarcă Fişiere Proprii"])

# Initialize session dataholders
orders_df, couriers_df = None, None

if mode == "Mod Demo (Date Test)":
    st.sidebar.info("Rulează aplicația folosind adrese preconfigurate din București și județul Ilfov.")
    orders_df, couriers_df = get_sample_data()
else:
    st.sidebar.markdown("### Încarcă Documente (.csv, .xlsx)")
    uploaded_orders = st.sidebar.file_uploader("Tabel Comenzi / Livrări", type=["csv", "xlsx"])
    uploaded_couriers = st.sidebar.file_uploader("Tabel Configurație Curieri", type=["csv", "xlsx"])
    
    if uploaded_orders and uploaded_couriers:
        try:
            if uploaded_orders.name.endswith('.csv'):
                orders_df = pd.read_csv(uploaded_orders)
            else:
                orders_df = pd.read_excel(uploaded_orders)
                
            if uploaded_couriers.name.endswith('.csv'):
                couriers_df = pd.read_csv(uploaded_couriers)
            else:
                couriers_df = pd.read_excel(uploaded_couriers)
        except Exception as e:
            st.sidebar.error(f"Eroare la procesarea fișierelor: {e}")

if orders_df is not None and couriers_df is not None:
    # Display preview tabs
    tab_ord, tab_cour = st.tabs(["📋 Vizualizare Comenzi Încărcate", "🛵 Configurație Curieri Activă"])
    with tab_ord:
        st.dataframe(orders_df, use_container_width=True)
    with tab_cour:
        st.dataframe(couriers_df, use_container_width=True)
        
    if st.button("🚀 Generează și Optimizează Traseele", type="primary"):
        routes_res, unrouted_res = generate_optimized_routes(orders_df, couriers_df)
        
        if routes_res is not None and not routes_res.empty:
            st.success("✅ Optimizare Finalizată cu Succes!")
            
            # KPI Analysis Summary Cards Grid Section
            st.markdown("### 📊 Rezumat Executiv Trasee")
            kpi_cols = st.columns(4)
            
            total_allocated = len(routes_res)
            unique_couriers = routes_res['Curier'].nunique()
            avg_stops = round(total_allocated / unique_couriers, 1) if unique_couriers > 0 else 0
            
            kpi_cols[0].metric("Total Livrări Alocate", total_allocated)
            kpi_cols[1].metric("Curieri Activi pe Traseu", unique_couriers)
            kpi_cols[2].metric("Medie Livrări / Curier", avg_stops)
            kpi_cols[3].metric("Comenzi Eșuate (Necesită Revizie)", len(unrouted_res))
            
            # Balance analysis table insight view
            st.markdown("#### ⚖️ Echilibrare Timp Clocks și Încarcare Operatională")
            balance_summary = []
            for c_name, group in routes_res.groupby('Curier'):
                balance_summary.append({
                    'Curier': c_name,
                    'Număr Comenzi': len(group),
                    'Prima Livrare': group['Ora_estimata_sosire'].min(),
                    'Ultima Livrare (Ora Finalizare)': group['Ora_estimata_sosire'].max(),
                    'Sloturi Acoperite': ", ".join(group['Slot_fix_livrare'].unique())
                })
            st.table(pd.DataFrame(balance_summary))
            
            # Main Track Table Output View Area
            st.markdown("### 🗺️ Ordinea detaliată a traseelor pe curieri")
            
            # Clean dataframe layout presentation view for users
            display_cols = ['Curier', 'Secventa', 'ID_Livrare', 'Client', 'Telefon', 
                            'Adresa_originala', 'Localitate_presupusa', 'Judet', 
                            'Ora_estimata_sosire', 'Slot_fix_livrare', 'Regula_slot_aplicata', 'Link_navigatie']
            
            # Intersect with available clean columns
            valid_display_cols = [c for c in display_cols if c in routes_res.columns]
            
            st.dataframe(routes_res[valid_display_cols].sort_values(by=['Curier', 'Secventa']), use_container_width=True)
            
            # Export Operations Download Controllers Trigger Arena
            st.markdown("### 💾 Export Planificări")
            
            csv_buffer = io.StringIO()
            routes_res[valid_display_cols].to_csv(csv_buffer, index=False, encoding='utf-8-sig')
            
            st.download_button(
                label="📥 Descarcă Fișier Trasee (Format CSV)",
                data=csv_buffer.getvalue(),
                file_name=f"Rute_Planificate_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )
            
            # Manual Review Panel Block Handler
            if not unrouted_res.empty:
                st.warning("⚠️ Adrese identificate care necesită atenție manuală:")
                st.dataframe(unrouted_res[['ID_Livrare', 'Client', 'Adresa_originala', 'Localitate_presupusa', 'Status']], use_container_width=True)
                
        else:
            st.error(f"Eroare în execuția algoritmului: {unrouted_res}")
else:
    st.info("💡 Vă rugăm să alegeți modul demo sau să încărcați fișierele de configurare din meniul din stânga pentru a rula optimizarea.")