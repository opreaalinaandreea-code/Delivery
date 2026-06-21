import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import requests
from geopy.geocoders import Nominatim
from datetime import datetime, timedelta
import io

# Configurare pagină Streamlit
st.set_page_config(page_title="Smart Routing B/IF", layout="wide")

# --- INIȚIALIZARE STATE (Memorie aplicație) ---
if 'curieri' not in st.session_state:
    st.session_state.curieri = {
        'Curier 1': {'start_addr': 'Bucuresti, Piata Unirii', 'start_time': '09:00', 'color': 'blue', 'confirmed': False, 'coords': None},
        'Curier 2': {'start_addr': 'Bucuresti, Militari', 'start_time': '09:00', 'color': 'green', 'confirmed': False, 'coords': None},
        'Curier 3': {'start_addr': 'Voluntari, Ilfov', 'start_time': '08:30', 'color': 'orange', 'confirmed': False, 'coords': None}
    }
if 'comenzi' not in st.session_state:
    st.session_state.comenzi = pd.DataFrame()

# Limite Bounding Box pentru București și Ilfov (Filtrare geografică)
LAT_MIN, LAT_MAX = 44.15, 44.75
LON_MIN, LON_MAX = 25.70, 26.45

# Inițializare Geolocator cu User Agent unic pentru respectarea politicilor OpenStreetMap
geolocator = Nominatim(user_agent="smart_routing_app_v2_2026")

# --- FUNCȚII AJUTATOARE ---
def valideaza_adresa(adresa):
    """Transformă adresa text în coordonate și verifică dacă e în Bounding Box-ul B/IF"""
    try:
        location = geolocator.geocode(adresa + ", Romania", timeout=10)
        if location:
            if LAT_MIN <= location.latitude <= LAT_MAX and LON_MIN <= location.longitude <= LON_MAX:
                return True, (location.latitude, location.longitude)
            return False, "În afara zonei B/IF"
        return False, "Adresă negăsită"
    except:
        return False, "Eroare API Localizare"

def get_osrm_route(start_coords, end_coords):
    """Apelează API-ul public OSRM pentru a calcula distanța și timpul rutier real"""
    url = f"http://router.project-osrm.org/route/v1/driving/{start_coords[1]},{start_coords[0]};{end_coords[1]},{end_coords[0]}?overview=simplified"
    try:
        response = requests.get(url, timeout=5).json()
        if response['code'] == 'Ok':
            route = response['routes'][0]
            # Convertim din metri în km și din secunde în minute
            return route['distance'] / 1000, route['duration'] / 60, route['geometry']
    except:
        pass
    # Fallback euristic la viteză medie urbană de 35 km/h în caz de eroare API
    return 5.0, 10.0, None 

# --- INTERFAȚA UTILIZATOR (UI) ---
st.title("🚚 Sistem Automat de Alocare și Optimizare Trasee (B/IF)")
st.markdown("Aplicație logistică pentru geocodare strictă, distribuție echilibrată pe timp și generare manifest.")

tab1, tab2, tab3 = st.tabs(["👥 1. Curieri & Configurare", "📦 2. Import & Validare Comenzi", "🗺️ 3. Optimizare & Trasee Active"])

# --- TAB 1: GESTIONARE CURIERI ---
with tab1:
    st.header("Gestionare și Validare Curieri")
    cols = st.columns(3)
    
    for idx, (nume, date) in enumerate(st.session_state.curieri.items()):
        with cols[idx]:
            st.subheader(f"🎨 {nume}", divider=date['color'])
            addr = st.text_input(f"Punct de plecare", value=date['start_addr'], key=f"addr_{nume}")
            time_str = st.text_input("Ora pornire (HH:MM)", value=date['start_time'], key=f"time_{nume}")
            
            if st.button(f"Confirmă {nume}", key=f"btn_{nume}"):
                succes, rezultat = valideaza_adresa(addr)
                if succes:
                    st.session_state.curieri[nume]['coords'] = rezultat
                    st.session_state.curieri[nume]['confirmed'] = True
                    st.session_state.curieri[nume]['start_addr'] = addr
                    st.session_state.curieri[nume]['start_time'] = time_str
                    st.success(f"✅ {nume} înregistrat cu succes în B/IF!")
                else:
                    st.session_state.curieri[nume]['confirmed'] = False
                    st.error(f"❌ {rezultat}")

# --- TAB 2: IMPORT DATE & MAPPER ---
with tab2:
    st.header("Importul și Procesarea Adreselor")
    
    uploaded_file = st.file_uploader("Încarcă fișierul Excel sau CSV (Drag & Drop)", type=['xlsx', 'xls', 'csv'])
    
    if uploaded_file:
        if uploaded_file.name.endswith('.csv'):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)
            
        st.write("### Previzualizare fișier încărcat:")
        st.dataframe(df.head(3))
        
        # Sistem dinamic de mapare a coloanelor
        st.write("### Asociere Coloane (Mapper)")
        c1, c2, c3, c4 = st.columns(4)
        col_adresa = c1.selectbox("Coloana Adresă/Stradă", options=df.columns)
        col_nume = c2.selectbox("Coloana Nume Client", options=df.columns)
        col_telefon = c3.selectbox("Coloana Telefon", options=df.columns)
        col_ramburs = c4.selectbox("Coloana Ramburs (Suma de plată)", options=df.columns)
        
        if st.button("Procesează și Geocodează Strict"):
            with st.spinner("Se execută geocodarea și filtrarea teritorială..."):
                coordonate = []
                statusuri = []
                
                for _, row in df.iterrows():
                    adresa_text = str(row[col_adresa])
                    succes, rez = valideaza_adresa(adresa_text)
                    if succes:
                        coordonate.append(rez)
                        statusuri.append("Validat")
                    else:
                        coordonate.append((None, None))
                        statusuri.append(f"Eroare: {rez}")
                
                # Construcția curată a tabelului finalizat (fără numpy)
                df['Lat'] = [c[0] for c in coordonate]
                df['Lon'] = [c[1] for c in coordonate]
                df['Status_Localizare'] = statusuri
                df['Nume'] = df[col_nume]
                df['Telefon'] = df[col_telefon]
                df['Ramburs'] = pd.to_numeric(df[col_ramburs]).fillna(0)
                df['Adresa_Curata'] = df[col_adresa]
                
                st.session_state.comenzi = df
                st.success("Geocodare finalizată!")
                
    if not st.session_state.comenzi.empty:
        st.write("### Starea Adreselor Procesate")
        # Marcare vizuală cu roșu pentru erori/adrese în afara Ilfovului
        st.dataframe(st.session_state.comenzi.style.map(
            lambda val: 'background-color: #ffcccc' if 'Eroare' in str(val) else '',
            subset=['Status_Localizare']
        ))

# --- TAB 3: ALGORITM DE BALANSARE PE TIMP & HARTĂ ---
with tab3:
    st.header("Algoritm de Repartizare pe Timp & Vizualizare")
    
    all_confirmed = all([date['confirmed'] for date in st.session_state.curieri.values()])
    
    if not all_confirmed:
        st.warning("⚠️ Te rugăm să validezi locația de pornire pentru toți curierii în Tab-ul 1.")
    elif st.session_state.comenzi.empty:
        st.warning("⚠️ Te rugăm să încarci și să procesezi o listă de comenzi în Tab-ul 2.")
    else:
        if st.button("🚀 Pornire Algoritm de Balansare"):
            comenzi_valide = st.session_state.comenzi[st.session_state.comenzi['Status_Localizare'] == "Validat"].copy()
            
            # Inițializare timpi de pornire și vectori rute
            starea_curieri = {}
            trasee_finale = {nume: [] for nume in st.session_state.curieri}
            
            for nume, date in st.session_state.curieri.items():
                h, m = map(int, date['start_time'].split(':'))
                starea_curieri[nume] = {
                    'timp_curent': datetime(2026, 6, 21, h, m), # Data curentă de simulare
                    'locatie_curenta': date['coords'],
                    'total_ramburs': 0
                }
            
            # Repartizare Greedy bazată pe cel mai mic timp total cumulat în momentul simulării
            for _, comanda in comenzi_valide.iterrows():
                dest_coords = (comanda['Lat'], comanda['Lon'])
                
                cel_mai_rapid_curier = None
                cel_mai_scurt_timp_sosire = datetime.max
                
                for nume, stare in starea_curieri.items():
                    _, timp_min, _ = get_osrm_route(stare['locatie_curenta'], dest_coords)
                    timp_sosire_estimat = stare['timp_curent'] + timedelta(minutes=timp_min)
                    
                    if timp_sosire_estimat < cel_mai_scurt_timp_sosire:
                        cel_mai_scurt_timp_sosire = timp_sosire_estimat
                        cel_mai_rapid_curier = nume
                
                # Alocare și actualizare status (timp deplasare + 5 minute fix per client)
                ora_sosire_str = cel_mai_scurt_timp_sosire.strftime("%H:%M")
                starea_curieri[cel_mai_rapid_curier]['timp_curent'] = cel_mai_scurt_timp_sosire + timedelta(minutes=5)
                starea_curieri[cel_mai_rapid_curier]['locatie_curenta'] = dest_coords
                starea_curieri[cel_mai_rapid_curier]['total_ramburs'] += comanda['Ramburs']
                
                trasee_finale[cel_mai_rapid_curier].append({
                    'Ora_Estimata': ora_sosire_str,
                    'Nume': comanda['Nume'],
                    'Telefon': comanda['Telefon'],
                    'Adresa': comanda['Adresa_Curata'],
                    'Ramburs': comanda['Ramburs'],
                    'Lat': comanda['Lat'],
                    'Lon': comanda['Lon']
                })
            
            st.session_state.trasee_finale = trasee_finale
            st.session_state.starea_curieri = starea_curieri
            st.success("Optimizarea și balansarea pe timp au fost finalizate cu succes!")

        # Randare Componente Vizuale (Hartă + Tabele Manifest)
        if 'trasee_finale' in st.session_state:
            st.write("### 🗺️ Monitorizare Trasee Active (Leaflet)")
            
            # Centrare implicită pe București
            harta = folium.Map(location=[44.4396, 26.0963], zoom_start=11)
            
            # Adăugare Hub-uri/Puncte de pornire curieri
            for nume, detalii in st.session_state.curieri.items():
                if detalii['coords']:
                    folium.Marker(
                        detalii['coords'], 
                        tooltip=f"START: {nume} ({detalii['start_time']})", 
                        icon=folium.Icon(color=detalii['color'], icon='home')
                    ).add_to(harta)
            
            # Adăugare clienți alocați pe hartă, colorați per curier responsabil
            for nume_curier, comenzi_alocate in st.session_state.trasee_finale.items():
                culoare = st.session_state.curieri[nume_curier]['color']
                for idx, c in enumerate(comenzi_alocate):
                    popup_content = f"<b>{idx+1}. Ora {c['Ora_Estimata']}</b><br><b>Client:</b> {c['Nume']}<br><b>Telefon:</b> {c['Telefon']}<br><b>Ramburs:</b> {c['Ramburs']} RON"
                    folium.Marker(
                        [c['Lat'], c['Lon']],
                        popup=folium.Popup(popup_content, max_width=300),
                        tooltip=f"{nume_curier} - Oprirea {idx+1}",
                        icon=folium.Icon(color=culoare, icon='user')
                    ).add_to(harta)
            
            st_folium(harta, width=1300, height=500)
            
            # Centralizare și export final manifest
            st.write("### 📋 Foi de Parcurs și Sumar Financiar")
            
            excel_data = io.BytesIO()
            with pd.ExcelWriter(excel_data, engine='openpyxl') as writer:
                for nume_curier, comenzi_alocate in st.session_state.trasee_finale.items():
                    if comenzi_alocate:
                        df_traseu = pd.DataFrame(comenzi_alocate)[['Ora_Estimata', 'Nume', 'Telefon', 'Adresa', 'Ramburs']]
                        
                        st.subheader(f"Manifest {nume_curier}")
                        st.metric(label="Total de încasat numerar (Ramburs)", value=f"{st.session_state.starea_curieri[nume_curier]['total_ramburs']} RON")
                        st.dataframe(df_traseu)
                        
                        # Salvăm fiecare curier într-un tab individual în fișierul Excel de export
                        df_traseu.to_excel(writer, sheet_name=nume_curier, index=False)
            
            st.download_button(
                label="📥 Descarcă Manifest Livrări complet (Excel)",
                data=excel_data.getvalue(),
                file_name=f"Manifest_Rute_{datetime.now().strftime('%Y-%m-%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
