import streamlit as st
import pandas as pd
import numpy as np
import math
import xml.etree.ElementTree as ET
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
        # Folosim tehnica de a ignora namespace-ul verificând doar terminarea tag-ului
        for elem in root.iter():
            tag_name = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            
            if tag_name == 'Placemark':
                # Extragem datele din interiorul acestui Placemark
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
            # Încercare disperată: căutare directă prin Regex dacă XML parserul a ignorat structura
            import re
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
        return None, "Nicio comandă din Excel nu s-a putut potrivi cu punctele din My Maps. Verificați ID-urile."

    while len(routable_items) > 0:
        best_score = float('inf')
        best_courier = None
        best_order_idx = None
        
        for idx, ord_item in enumerate(routable_items):
            for _, c_row in active_couriers.iterrows():
                c_id = c_row['Curier_ID']
                max_capacity = int(c_row['Capacitate_max_livrari'])
                
                if courier_counts[c_id] >= max_capacity:
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
            
        chosen_order = routable_items.pop(best_order_idx)
        chosen_order['Curier_alocat'] = best_courier
        courier_tracks[best_courier].append(chosen_order)
        courier_counts[best_courier] += 1

    # Dacă rămân ordine din lipsă de capacitate
    for left_item in routable_items:
        left_item['Status'] = 'Depășire Capacitate (Maxim 20/curier)'
        unroutable = pd.concat([unroutable, pd.DataFrame([left_item])], ignore_index=True)

    final_route_records = []
    
    for _, c_row in active_couriers.iterrows():
        c_id = c_row['Curier_ID']
        track = courier_tracks[c_id]
        if not track:
            continue
            
        # Sortează traseul (Nearest Neighbor)
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
                
            applied_slot = windows[current_window_idx][2] if current_window_idx < len(windows) else "După 20:00"
            
            stop['Curier'] = c_row['Nume_curier']
            stop['Secventa'] = seq
            stop['Ora_estimata_sosire'] = arrival_time_str
            stop['Slot_fix_livrare'] = applied_slot
            stop['Regula_slot_aplicata'] = "Păstrat în primul slot" if seq <= 2 else "Alocat dinamic"
            stop['Link_navigatie'] = f"http://maps.google.com/?q={stop['Latitudine']},{stop['Longitudine']}"
            stop['Status'] = 'Optimizat Exact'
            
            final_route_records.append(stop)
            current_time += timedelta(minutes=20) # 10 min stop + 10 min buffer

    df_routed = pd.DataFrame(final_route_records) if final_route_records else pd.DataFrame()
    
    if not df_routed.empty and not unroutable.empty:
        df_final_output = pd.concat([df_routed, unroutable], ignore_index=True)
    elif not df_routed.empty:
        df_final_output = df_routed
    else:
        df_final_output = unroutable

    new_system_cols = ['Curier', 'Secventa', 'Ora_estimata_sosire', 'Slot_fix_livrare', 'Regula_slot_aplicata', 'Link_navigatie', 'Status', 'Latitudine', 'Longitudine']
    final_cols_order = original_columns + [c for c in new_system_cols if c not in original_columns]
    existing_cols_order = [c for c in final_cols_order if c in df_final_output.columns]
    
    return df_final_output[existing_cols_order], unroutable

# --- UI Interface ---
st.title("🚚 RoRoute - Planificator Automat (Excel + Google My Maps)")
st.subheader("Sistem profesional bazat pe coordonate exacte verificate")

import re

# Încarcă ambele fișiere simultan
st.sidebar.markdown("### 📋 Încărcare Date Sincronizate")
uploaded_excel = st.sidebar.file_uploader("1. Încarcă Tabelul Excel/CSV cu Comenzi", type=["csv", "xlsx"])
uploaded_kml = st.sidebar.file_uploader("2. Încarcă Harta KML din Google My Maps", type=["kml"])

orders_final_df = None
original_columns_list = []

if uploaded_excel and uploaded_kml:
    # Pasul A: Citire tabel comenzi original
    if uploaded_excel.name.endswith('.csv'):
        df_raw = pd.read_csv(uploaded_excel)
    else:
        df_raw = pd.read_excel(uploaded_excel)
        
    orders_mapped, original_columns_list = standardize_orders_df(df_raw)
    
    # Pasul B: Citire fișier KML din My Maps
    kml_df, err = parse_kml_flexible(uploaded_kml)
    
    if err:
        st.error(err)
    else:
        # Pasul C: Corelarea inteligentă între Excel și My Maps
        # Ne asigurăm că ID-urile sunt comparate curat sub formă de text curățat
        orders_mapped['ID_String_Match'] = orders_mapped['ID_Livrare'].astype(str).str.strip().str.lower()
        kml_df['ID_String_Match'] = kml_df['ID_KML_Potrivire'].astype(str).str.strip().str.lower()
        
        # Eliminăm duplicatele din KML pentru a nu multiplica rândurile din Excel
        kml_df = kml_df.drop_duplicates(subset=['ID_String_Match'])
        
        # Facem îmbinarea datelor (Merge) păstrând TOATE rândurile din Excel
        merged_df = pd.merge(orders_mapped, kml_df[['ID_String_Match', 'Latitudine', 'Longitudine']], on='ID_String_Match', how='left')
        merged_df.drop(columns=['ID_String_Match'], errors='ignore')
        
        orders_final_df = merged_df
        st.sidebar.success(f"📊 S-au conectat cu succes datele din Excel cu hărțile!")

# Afișare interfață de control
if orders_final_df is not None:
    st.info("✨ Datele din ambele fișiere au fost corelate. Puteți lansa optimizarea traseelor.")
    
    if st.button("🚀 Generează Traseele Optimizate", type="primary"):
        routes_res, unrouted_df = generate_optimized_routes(orders_final_df, original_columns_list)
        
        if routes_res is not None and not routes_res.empty:
            st.success("✅ Algoritmul a finalizat organizarea curierilor!")
            
            # KPI Cards
            routes_only = routes_res[routes_res['Status'] == 'Optimizat Exact']
            total_allocated = len(routes_only)
            
            kpi_cols = st.columns(3)
            kpi_cols[0].metric("Total Comenzi Alocate", total_allocated)
            kpi_cols[1].metric("Curieri Pe Traseu", routes_only['Curier'].nunique() if total_allocated > 0 else 0)
            kpi_cols[2].metric("Comenzi fără coordonate în KML", len(routes_res[routes_res['Status'] != 'Optimizat Exact']))
            
            # Mapă Interactivă
            if total_allocated > 0:
                st.markdown("### 🗺️ Vizualizare Trasee Curieri")
                map_data = routes_only[['Latitudine', 'Longitudine']].dropna().rename(columns={'Latitudine': 'latitude', 'Longitudine': 'longitude'})
                st.map(map_data)
                
                st.markdown("#### ⚖️ Timpi de Finalizare și Încărcare")
                balance_summary = []
                for c_name, group in routes_only.groupby('Curier'):
                    balance_summary.append({
                        'Curier': c_name,
                        'Număr Comenzi': len(group),
                        'Prima Livrare': group['Ora_estimata_sosire'].min(),
                        'Ultima Livrare (Ora Finish)': group['Ora_estimata_sosire'].max(),
                        'Sloturi Orice': ", ".join(group['Slot_fix_livrare'].astype(str).unique())
                    })
                st.table(pd.DataFrame(balance_summary))
            
            # Alerte
            unmatched_addresses = routes_res[routes_res['Status'] != 'Optimizat Exact']
            if not unmatched_addresses.empty:
                st.warning("⚠️ Următoarele comenzi din Excel nu au fost găsite în fișierul KML (Verificați dacă Numele punctului din My Maps coincide cu Nr. Comandă din Excel):")
                st.dataframe(unmatched_addresses[['ID_Livrare', 'Client', 'Adresa_originala']], use_container_width=True)

            st.markdown("### 🗺️ Tabel Trasee Finale (Conține toate coloanele tale originale)")
            st.dataframe(routes_res.sort_values(by=['Curier', 'Secventa']), use_container_width=True)
            
            csv_buffer = io.StringIO()
            routes_res.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
            st.download_button(
                label="📥 Descarcă Fișier Trasee Complet (Format CSV)",
                data=csv_buffer.getvalue(),
                file_name=f"Trasee_Complete_MyMaps_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )
else:
    st.info("💡 Pentru a rula optimizarea exactă, vă rugăm să încărcați în bara din stânga AMBELE fișiere: Tabelul Excel de comenzi și Fișierul KML exportat din My Maps.")
