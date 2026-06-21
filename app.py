import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import requests
from geopy.geocoders import Nominatim
from datetime import datetime, timedelta
import io
import sqlite3
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

st.set_page_config(page_title="Smart Routing Pro B/IF", layout="wide")

# --- 1. CONFIGURARE BAZĂ DE DATE (CACHE ADRESE) ---
def init_db():
    conn = sqlite3.connect('cache_adrese.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS geocache (
            adresa TEXT PRIMARY KEY,
            lat REAL,
            lon REAL
        )
    ''')
    conn.commit()
    conn.close()

def get_cached_coords(adresa):
    conn = sqlite3.connect('cache_adrese.db')
    cursor = conn.cursor()
    cursor.execute('SELECT lat, lon FROM geocache WHERE adresa = ?', (adresa,))
    row = cursor.fetchone()
    conn.close()
    return row if row else None

def set_cached_coords(adresa, lat, lon):
    conn = sqlite3.connect('cache_adrese.db')
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT OR REPLACE INTO geocache (adresa, lat, lon) VALUES (?, ?, ?)', (adresa, lat, lon))
        conn.commit()
    except:
        pass
    conn.close()

init_db()

# --- INITIALIZARE STATE ---
if 'curieri' not in st.session_state:
    st.session_state.curieri = {
        'Curier 1': {'start_addr': 'Bucuresti, Piata Unirii', 'start_time': '09:00', 'color': 'blue', 'confirmed': False, 'coords': None},
        'Curier 2': {'start_addr': 'Bucuresti, Militari', 'start_time': '09:00', 'color': 'green', 'confirmed': False, 'coords': None},
        'Curier 3': {'start_addr': 'Voluntari, Ilfov', 'start_time': '08:30', 'color': 'orange', 'confirmed': False, 'coords': None}
    }
if 'comenzi' not in st.session_state:
    st.session_state.comenzi = pd.DataFrame()

LAT_MIN, LAT_MAX = 44.15, 44.75
LON_MIN, LON_MAX = 25.70, 26.45
geolocator = Nominatim(user_agent="smart_routing_enterprise_2026")

# --- GEOCRARE CU INTEGRARE CACHE ---
def valideaza_adresa(adresa):
    adresa_curata = adresa.strip().lower()
    
    # Încercăm să luăm din Cache-ul SQL local (0 ms timp de așteptare)
    cached = get_cached_coords(adresa_curata)
    if cached:
        return True, cached

    # Dacă nu există în cache, apelăm API-ul extern
    try:
        location = geolocator.geocode(adresa + ", Romania", timeout=10)
        if location:
            if LAT_MIN <= location.latitude <= LAT_MAX and LON_MIN <= location.longitude <= LON_MAX:
                set_cached_coords(adresa_curata, location.latitude, location.longitude)
                return True, (location.latitude, location.longitude)
            return False, "În afara zonei B/IF"
        return False, "Adresă negăsită"
    except:
        return False, "Eroare API"

def get_osrm_time(start_coords, end_coords):
    url = f"http://router.project-osrm.org/route/v1/driving/{start_coords[1]},{start_coords[0]};{end_coords[1]},{end_coords[0]}?overview=false"
    try:
        response = requests.get(url, timeout=3).json()
        if response['code'] == 'Ok':
            return int(response['routes'][0]['duration'] / 60) # Returnează minute întregi
    except:
        pass
    return 15 # Fallback urban standard generic în minute

# --- INTERFAȚĂ ---
st.title("🚀 Smart Routing Enterprise (OR-Tools & SQL Cache)")

tab1, tab2, tab3 = st.tabs(["👥 1. Flotă Curieri", "📦 2. Import Inteligent", "🗺️ 3. Optimizare Matematică"])

with tab1:
    st.header("Configurare Flotă")
    cols = st.columns(3)
    for idx, (nume, date) in enumerate(st.session_state.curieri.items()):
        with cols[idx]:
            st.subheader(f"🎨 {nume}", divider=date['color'])
            addr = st.text_input(f"Locație Start", value=date['start_addr'], key=f"addr_{nume}")
            time_str = st.text_input("Ora Start (HH:MM)", value=date['start_time'], key=f"time_{nume}")
            if st.button(f"Validează {nume}", key=f"btn_{nume}"):
                succes, rez = valideaza_adresa(addr)
                if succes:
                    st.session_state.curieri[nume].update({'coords': rez, 'confirmed': True, 'start_addr': addr, 'start_time': time_str})
                    st.success("✅ Validat!")
                else:
                    st.error(f"❌ {rez}")

with tab2:
    st.header("Procesare Date")
    uploaded_file = st.file_uploader("Încarcă fișier comenzi", type=['xlsx', 'csv'])
    if uploaded_file:
        df = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
        c1, c2, c3, c4 = st.columns(4)
        col_adresa = c1.selectbox("Adresă", options=df.columns)
        col_nume = c2.selectbox("Nume", options=df.columns)
        col_telefon = c3.selectbox("Telefon", options=df.columns)
        col_ramburs = c4.selectbox("Ramburs", options=df.columns)
        
        if st.button("Rulare Geocodare Inteligentă"):
            coordonate, statusuri = [], []
            progress_bar = st.progress(0)
            
            for i, row in df.iterrows():
                succes, rez = valideaza_adresa(str(row[col_adresa]))
                coordonate.append(rez if succes else (None, None))
                statusuri.append("Validat" if succes else f"Eroare: {rez}")
                progress_bar.progress((i + 1) / len(df))
                
            df['Lat'] = [c[0] for c in coordonate]
            df['Lon'] = [c[1] for c in coordonate]
            df['Status_Localizare'] = statusuri
            df['Nume'] = df[col_nume]
            df['Telefon'] = df[col_telefon]
            df['Ramburs'] = pd.to_numeric(df[col_ramburs]).fillna(0)
            df['Adresa_Curata'] = df[col_adresa]
            st.session_state.comenzi = df
            st.success("Geocodare completă (adresele noi au fost salvate în baza de date SQL locală).")

    if not st.session_state.comenzi.empty:
        st.dataframe(st.session_state.comenzi.style.map(lambda v: 'background-color: #ffcccc' if 'Eroare' in str(v) else '', subset=['Status_Localizare']))

with tab3:
    st.header("Motor de Optimizare Globală")
    if not all([d['confirmed'] for d in st.session_state.curieri.values()]) or st.session_state.comenzi.empty:
        st.warning("Asigură-te că ai curierii validați și comenzile încărcate.")
    else:
        if st.button("🚀 Generează Trasee Optime (Google OR-Tools)"):
            comenzi_valide = st.session_state.comenzi[st.session_state.comenzi['Status_Localizare'] == "Validat"].copy().reset_index(drop=True)
            
            # --- CONSTRUIRE MATRICE DE TIMPI ---
            # Colectăm toate punctele: Punctele de start ale curierilor, urmate de clienți
            list_curieri = list(st.session_state.curieri.items())
            puncte_start = [date['coords'] for nume, date in list_curieri]
            puncte_clienti = [(row['Lat'], row['Lon']) for _, row in comenzi_valide.iterrows()]
            toate_punctele = puncte_start + puncte_clienti
            
            num_locations = len(toate_punctele)
            num_vehicles = len(list_curieri)
            
            # Matricea de costuri (timp condus + 5 minute fix per drop-off la clienți)
            matrix = []
            for i in range(num_locations):
                row_matrix = []
                for j in range(num_locations):
                    if i == j:
                        row_matrix.append(0)
                    else:
                        timp_condus = get_osrm_time(toate_punctele[i], toate_punctele[j])
                        # Adăugăm 5 minute timp de servire doar dacă destinația (j) este un client
                        timp_servire = 5 if j >= num_vehicles else 0
                        row_matrix.append(timp_condus + timp_servire)
                matrix.append(row_matrix)
                
            # --- REZOLVARE VRP CU GOOGLE OR-TOOLS ---
            manager = pywrapcp.RoutingIndexManager(num_locations, num_vehicles, list(range(num_vehicles)), list(range(num_vehicles)))
            routing = pywrapcp.RoutingModel(manager)
            
            def time_callback(from_index, to_index):
                return matrix[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)]
                
            transit_callback_index = routing.RegisterTransitCallback(time_callback)
            routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)
            
            # Adăugăm dimensiunea de timp pentru balansare corectă
            routing.AddDimension(transit_callback_index, 0, 480, True, "Time") # Maxim 8 ore (480 min) per traseu
            time_dimension = routing.GetDimensionOrDie("Time")
            time_dimension.SetGlobalSpanCostCoefficient(100) # Forțează algoritmul să egaleze timpii totali între curieri
            
            search_parameters = pywrapcp.DefaultRoutingSearchParameters()
            search_parameters.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
            
            solution = routing.SolveWithParameters(search_parameters)
            
            # --- PROCESARE REZULTATE SOLVER ---
            if solution:
                trasee_finale = {nume: [] for nume in st.session_state.curieri}
                starea_curieri = {}
                
                for veh_id in range(num_vehicles):
                    nume_curier = list_curieri[veh_id][0]
                    date_curier = list_curieri[veh_id][1]
                    h, m = map(int, date_curier['start_time'].split(':'))
                    timp_acumulat = datetime(2026, 6, 21, h, m)
                    
                    index = routing.Start(veh_id)
                    index = solution.Value(routing.NextVar(index)) # Sărim peste punctul de start în sine
                    
                    total_cash = 0
                    while not routing.IsEnd(index):
                        node_id = manager.IndexToNode(index)
                        client_idx = node_id - num_vehicles
                        comanda = comenzi_valide.iloc[client_idx]
                        
                        # Calculăm ora estimată de sosire reală
                        prev_node = manager.IndexToNode(solution.Value(routing.PrevVar(index))) if routing.Start(veh_id) != routing.PrevVar(index) else veh_id
                        timp_deplasare = matrix[prev_node][node_id]
                        timp_acumulat += timedelta(minutes=int(timp_deplasare))
                        
                        trasee_finale[nume_curier].append({
                            'Ora_Estimata': timp_acumulat.strftime("%H:%M"),
                            'Nume': comanda['Nume'],
                            'Telefon': comanda['Telefon'],
                            'Adresa': comanda['Adresa_Curata'],
                            'Ramburs': comanda['Ramburs'],
                            'Lat': comanda['Lat'],
                            'Lon': comanda['Lon']
                        })
                        
                        total_cash += comanda['Ramburs']
                        index = solution.Value(routing.NextVar(index))
                        
                    starea_curieri[nume_curier] = {'total_ramburs': total_cash}
                    
                st.session_state.trasee_finale = trasee_finale
                st.session_state.starea_curieri = starea_curieri
                st.success("Matricea globală a fost optimizată cu succes!")

        # --- AFIȘARE HĂRȚI ȘI LINK-URI DE NAVIGAȚIE GPS ---
        if 'trasee_finale' in st.session_state:
            m = folium.Map(location=[44.4396, 26.0963], zoom_start=11)
            for nume, date in st.session_state.curieri.items():
                if date['coords']:
                    folium.Marker(date['coords'], tooltip=f"START: {nume}", icon=folium.Icon(color=date['color'], icon='home')).add_to(m)
            
            for nume_curier, comenzi in st.session_state.trasee_finale.items():
                culoare = st.session_state.curieri[nume_curier]['color']
                for idx, c in enumerate(comenzi):
                    waze_url = f"https://waze.com/ul?ll={c['Lat']},{c['Lon']}&navigate=yes"
                    gmaps_url = f"https://www.google.com/maps/search/?api=1&query={c['Lat']},{c['Lon']}"
                    
                    popup_html = f"""
                    <b>{idx+1}. Ora {c['Ora_Estimata']}</b><br>
                    Client: {c['Nume']}<br>
                    Telefon: {c['Telefon']}<br>
                    <a href='{waze_url}' target='_blank' style='color: #2da1c7; font-weight:bold;'>🚗 Deschide în Waze</a><br>
                    <a href='{gmaps_url}' target='_blank' style='color: #4285F4; font-weight:bold;'>🗺️ Deschide în Google Maps</a>
                    """
                    folium.Marker([c['Lat'], c['Lon']], popup=folium.Popup(popup_html, max_width=250), icon=folium.Icon(color=culoare, icon='user')).add_to(m)
            
            st_folium(m, width=1300, height=500)
            
            # Generare foi de parcurs
            for nume_curier, comenzi in st.session_state.trasee_finale.items():
                if comenzi:
                    st.subheader(f"📋 Traseu {nume_curier}")
                    st.metric("Total Încasat Cash", f"{st.session_state.starea_curieri[nume_curier]['total_ramburs']} RON")
                    st.dataframe(pd.DataFrame(comenzi)[['Ora_Estimata', 'Nume', 'Telefon', 'Adresa', 'Ramburs']])
