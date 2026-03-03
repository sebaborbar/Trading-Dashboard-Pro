import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import math
import altair as alt

# --- 1. CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Trading Dashboard", layout="wide", page_icon="📈")

# --- 🔒 SISTEMA DE LOGIN MULTIUSUARIO ---
if 'logeado' not in st.session_state:
    st.session_state['logeado'] = False

if not st.session_state['logeado']:
    st.markdown("<h1 style='text-align: center;'>🔒 Acceso al Trading Dashboard</h1>", unsafe_allow_html=True)
    st.write("---")
    
    col1, col2, col3 = st.columns([1, 1.5, 1])
    with col2:
        st.info("Ingresa tus credenciales para acceder a la bóveda de operaciones.")
        with st.form("form_login"):
            usuario = st.text_input("Usuario")
            password = st.text_input("Contraseña", type="password")
            submit = st.form_submit_button("Ingresar 🚀")
            
            if submit:
                # 📝 DICCIONARIO DE ALUMNOS (Usuario : Contraseña)
                usuarios_autorizados = {
                    "Sebastian": "Traders2026!",
                    "Juan Perez": "Swing2026*",
                    "MariaTrader": "Breakout123"
                }
                
                if usuario in usuarios_autorizados and usuarios_autorizados[usuario] == password:
                    st.session_state['logeado'] = True
                    st.session_state['usuario_actual'] = usuario
                    st.rerun()
                else:
                    st.error("⚠️ Usuario o contraseña incorrectos.")
                    
    # Si no está logeado, st.stop() bloquea que se cargue el resto del código
    st.stop()

# --- SI EL LOGIN ES EXITOSO, LA APP CONTINÚA AQUÍ ---
usuario_actual = st.session_state['usuario_actual']

st.sidebar.title("👤 Perfil")
st.sidebar.success(f"🟢 Sesión activa: {usuario_actual}")
if st.sidebar.button("🚪 Cerrar Sesión"):
    st.session_state['logeado'] = False
    st.rerun()

st.title(f"📈 TRADING DASHBOARD | {usuario_actual}")
st.write("---")

# --- FUNCIONES AUXILIARES ---
def formato_es(num):
# ... (de aquí para abajo tu código sigue exactamente igual)
    return f"{num:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def formato_entero(num):
    return f"{num:,}".replace(",", ".")

# ---  2. CONEXIÓN A GOOGLE SHEETS ---
try:
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    import os
    
    # EL TRUCO DEL FANTASMA: Recreamos el archivo original por 1 segundo
    with open("temp_credenciales.json", "w") as f:
        f.write(st.secrets["google_json"])
        
    # Usamos LA MISMA función original que te funcionó el primer día
    creds = Credentials.from_service_account_file("temp_credenciales.json", scopes=scopes)
    
    # Destruimos la evidencia inmediatamente
    os.remove("temp_credenciales.json")
    
    client = gspread.authorize(creds)
    sheet = client.open("DB_Trading_App").worksheet("journal")
    conexion_exitosa = True

    # FIX CÓNDOR CHILENO: Limpiamos los datos globalmente
    filas = sheet.get_all_values()
    if len(filas) > 1:
        df = pd.DataFrame(filas[1:], columns=filas[0])
        df.columns = df.columns.str.strip()
        
        cols_numericas = ['Acciones', 'Precio Entrada', 'Precio Salida', 'P/L %', 'P/L $']
        for col in cols_numericas:
            if col in df.columns:
                df[col] = df[col].astype(str).str.replace('$', '', regex=False).str.replace('%', '', regex=False)
                df[col] = df[col].str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    else:
        df = pd.DataFrame()
        
except Exception as e:
    conexion_exitosa = False
    df = pd.DataFrame()
    st.sidebar.error(f"Error de base de datos: {e}")

# 🔒 GUARDIÁN DE PRIVACIDAD: Filtramos el Excel para mostrar SOLO los datos del usuario activo
if 'Usuario' in df.columns:
    df = df[df['Usuario'] == usuario_actual]

# --- 3. MENÚ DE NAVEGACIÓN ---
tab_calc, tab_bitacora, tab_dash = st.tabs(["🧮 Calculadora de Riesgo", "📝 Bitácora", "📊 Métricas de Rendimiento"])

# ==========================================
# PESTAÑA 1: CALCULADORA DE RIESGO
# ==========================================
with tab_calc:
            st.subheader("⚙️ Configuración del Trade")
            
            # 1. EL SWITCH INSTITUCIONAL
            direccion = st.radio("Dirección del Trade:", ["ALZA 🟢 (Long)", "BAJA 🔴 (Short)"], horizontal=True)

            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**1. Datos del Capital**")
                capital = st.number_input("Capital Total ($)", min_value=0.0, value=30000.0, step=1000.0)
                riesgo_pct = st.number_input("Riesgo (%)", min_value=0.1, value=0.50, step=0.1)
                riesgo_usd = capital * (riesgo_pct / 100)
                st.info(f"**Riesgo en dinero:** ${formato_es(riesgo_usd)}")

            with col2:
                st.markdown("**2. Datos del Gráfico**")
                ticker = st.text_input("TICKER", value="AAAA").upper()
                breakout = st.number_input("Precio Breakout/Breakdown ($)", min_value=0.0, value=50.0, step=0.5)
                atr = st.number_input("ATR ($)", min_value=0.0, value=4.89, step=0.1)
                
                # Texto dinámico según la dirección
                if "ALZA" in direccion:
                    extremo = st.number_input("Precio Último Mínimo ($)", min_value=0.0, value=46.0, step=0.5)
                else:
                    extremo = st.number_input("Precio Último Máximo ($)", min_value=0.0, value=54.0, step=0.5)

            st.write("---")
            
            # 2. LA MAGIA MATEMÁTICA (CON TUS MULTIPLICADORES)
            if breakout > 0 and extremo > 0:
                if "ALZA" in direccion:
                    entrada = breakout * 1.001
                    sl_extremo = extremo * 0.995
                    sl_atr = breakout - atr
                    sl_definitivo = min(sl_extremo, sl_atr) # Stop más lejano hacia abajo
                    
                    if entrada > sl_definitivo and sl_definitivo > 0:
                        riesgo_por_accion = entrada - sl_definitivo
                        acciones_a_comprar = math.floor(riesgo_usd / riesgo_por_accion)
                        monto_exposicion = acciones_a_comprar * entrada
                        take_profit = entrada + (riesgo_por_accion * 2)
                        acciones_vender_tp = math.ceil(acciones_a_comprar / 2)
                        
                        texto_accion = "COMPRAR"
                        texto_salida = "VENDER"
                else:
                    # MATEMÁTICA INVERTIDA PARA CORTOS
                    entrada = breakout * 0.999 # Entramos un pelito más abajo de la ruptura
                    sl_extremo = extremo * 1.005 # Le damos un respiro al máximo
                    sl_atr = breakout + atr
                    sl_definitivo = max(sl_extremo, sl_atr) # Stop más lejano hacia arriba
                    
                    if sl_definitivo > entrada and entrada > 0:
                        riesgo_por_accion = sl_definitivo - entrada
                        acciones_a_comprar = math.floor(riesgo_usd / riesgo_por_accion)
                        monto_exposicion = acciones_a_comprar * entrada
                        take_profit = entrada - (riesgo_por_accion * 2)
                        acciones_vender_tp = math.ceil(acciones_a_comprar / 2)
                        
                        texto_accion = "VENDER EN CORTO"
                        texto_salida = "COMPRAR PARA CUBRIR"

                # 3. MOSTRAR RESULTADOS
                try:
                    import math # Aseguramos que la librería esté cargada
                    acc_str = formato_entero(acciones_a_comprar)
                    acc_tp_str = formato_entero(acciones_vender_tp)
                    
                    st.subheader("Plan de Acción")
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Acciones", f"{acc_str}")
                    c2.metric("Entrada", f"${formato_es(entrada)}")
                    c3.metric("Stop Loss", f"${formato_es(sl_definitivo)}")
                    c4.metric("Take Profit (2:1)", f"${formato_es(take_profit)}")
                    
                    st.success(f"**Resumen de Ejecución:** Debes **{texto_accion} {acc_str} acciones** de {ticker} a **${formato_es(entrada)}**. Tu exposición de capital será de **${formato_es(monto_exposicion)}**. Al llegar a tu objetivo, debes **{texto_salida} {acc_tp_str} acciones** para asegurar tu ganancia.")
                except NameError:
                    st.error("🚨 Esperando datos lógicos: Para ALZA, el Mínimo debe ser menor al Breakout. Para BAJA, el Máximo debe ser mayor al Breakout.")

# ==========================================
# PESTAÑA 2: BITÁCORA (Nueva Arquitectura)
# ==========================================
with tab_bitacora:
    # El Selector Mágico (Orden corregido y texto limpio)
    modo_bitacora = st.radio(
        "🎛️ Selecciona tu modo de trabajo:",
        ["⏪ Registro Histórico", "🟢 Gestión en Vivo (Portafolio)"],
        horizontal=True
    )
    st.write("---")

    if modo_bitacora == "⏪ Registro Histórico":
        # --- MODO 1: REGISTRO HISTÓRICO ---
        st.subheader("📝 Registro Histórico")
        st.markdown("Ideal para subir trades antiguos o migrar historiales.")
        
        with st.form("form_trade_avanzado", clear_on_submit=True):
            st.markdown("#### 1. Datos de Entrada")
            col1, col2, col3, col4 = st.columns(4)
            with col1: fecha_entrada = st.date_input("Fecha de Compra")
            with col2: ticker_form = st.text_input("Ticker (Ej: NVDA)").upper()
            with col3: acciones_totales = st.number_input("Total Acciones", min_value=0, step=1)
            with col4: precio_entrada_form = st.number_input("Precio Compra ($)", min_value=0.00, step=0.50)
                
            notas_entrada = st.text_input("Notas de Entrada")
            st.markdown("---")
            
            st.markdown("#### 2. Salidas Parciales")
            s1_c1, s1_c2, s1_c3, s1_c4 = st.columns(4)
            with s1_c1: fecha_s1 = st.date_input("Fecha Salida 1", key="f1")
            with s1_c2: acc_s1 = st.number_input("Acciones Vendidas", min_value=0, step=1, key="a1")
            with s1_c3: precio_s1 = st.number_input("Precio Venta ($)", min_value=0.0, step=0.5, key="p1")
            with s1_c4: notas_s1 = st.text_input("Notas Salida 1", key="n1")
            
            s2_c1, s2_c2, s2_c3, s2_c4 = st.columns(4)
            with s2_c1: fecha_s2 = st.date_input("Fecha Salida 2", key="f2")
            with s2_c2: acc_s2 = st.number_input("Acciones Vendidas", min_value=0, step=1, key="a2")
            with s2_c3: precio_s2 = st.number_input("Precio Venta ($)", min_value=0.0, step=0.5, key="p2")
            with s2_c4: notas_s2 = st.text_input("Notas Salida 2", key="n2")

            s3_c1, s3_c2, s3_c3, s3_c4 = st.columns(4)
            with s3_c1: fecha_s3 = st.date_input("Fecha Salida 3", key="f3")
            with s3_c2: acc_s3 = st.number_input("Acciones Vendidas", min_value=0, step=1, key="a3")
            with s3_c3: precio_s3 = st.number_input("Precio Venta ($)", min_value=0.0, step=0.5, key="p3")
            with s3_c4: notas_s3 = st.text_input("Notas Salida 3", key="n3")
            
            st.write("---")
            submit_button = st.form_submit_button("💾 Guardar Historial en Base de Datos")
            
            if submit_button:
                if ticker_form == "" or precio_entrada_form <= 0 or acciones_totales <= 0:
                    st.warning("⚠️ Ingresa un Ticker, acciones y precio válidos.")
                elif (acc_s1 + acc_s2 + acc_s3) > acciones_totales:
                    st.error("⚠️ Error: Vendiste más acciones de las que compraste.")
                else:
                    filas_a_guardar = []
                    monto_entrada = acciones_totales * precio_entrada_form
                    filas_a_guardar.append([str(fecha_entrada), ticker_form, acciones_totales, precio_entrada_form, monto_entrada, 0.0, 0.0, 0.0, notas_entrada, usuario_actual])
                    
                    def procesar_salida(f_fecha, f_acc, f_precio, f_notas):
                        if f_acc > 0 and f_precio > 0:
                            monto_salida = f_acc * precio_entrada_form
                            pl_usd = (f_precio - precio_entrada_form) * f_acc
                            pl_pct = ((f_precio - precio_entrada_form) / precio_entrada_form) * 100
                            return [str(f_fecha), ticker_form, f_acc, precio_entrada_form, monto_salida, f_precio, round(pl_pct, 2), round(pl_usd, 2), f_notas, usuario_actual]
                        return None
                    
                    s1 = procesar_salida(fecha_s1, acc_s1, precio_s1, notas_s1)
                    if s1: filas_a_guardar.append(s1)
                    s2 = procesar_salida(fecha_s2, acc_s2, precio_s2, notas_s2)
                    if s2: filas_a_guardar.append(s2)
                    s3 = procesar_salida(fecha_s3, acc_s3, precio_s3, notas_s3)
                    if s3: filas_a_guardar.append(s3)
                    
                    try:
                        sheet.append_rows(filas_a_guardar)
                        st.success(f"¡Éxito! Se registraron {len(filas_a_guardar)} filas para {ticker_form}.")
                    except Exception as e:
                        st.error(f"Hubo un problema con Google Sheets: {e}")

    else:
        # --- MODO 2: GESTIÓN EN VIVO (Gestor de Portafolio) ---
        col_izq, col_der = st.columns([1, 1.2])
        
        with col_izq:
            st.markdown("#### 🚀 Abrir Nueva Operación")
            st.markdown("Dispara tu entrada al mercado aquí.")
            with st.form("form_abrir_trade", clear_on_submit=True):
                f_compra = st.date_input("Fecha de Compra")
                t_compra = st.text_input("Ticker (Ej: TSLA)").upper()
                a_compra = st.number_input("Cantidad de Acciones", min_value=1, step=1)
                p_compra = st.number_input("Precio de Compra ($)", min_value=0.01, step=0.01)
                n_compra = st.text_input("Notas Iniciales (Ej: Breakout VCP)")
                
                btn_abrir = st.form_submit_button("🛒 Entrar al Mercado")
                
                if btn_abrir:
                    if t_compra != "" and p_compra > 0:
                        monto = a_compra * p_compra
                        # Precio salida y P/L se envían como 0.0 para marcarlo como Posición Abierta
                        fila = [str(f_compra), t_compra, a_compra, p_compra, monto, 0.0, 0.0, 0.0, n_compra, usuario_actual]
                        try:
                            sheet.append_row(fila)
                            st.success(f"¡Posición abierta! Presiona **F5** para ver a {t_compra} en tu Portafolio.")
                        except Exception as e:
                            st.error(f"Error: {e}")
                    else:
                        st.warning("⚠️ Revisa el Ticker y el precio.")

        with col_der:
            st.markdown("#### 💼 Portafolio Activo")
            if conexion_exitosa and not df.empty:
                # El cerebro del Portafolio: Calcula qué está abierto y qué está cerrado
                portafolio = {}
                for t in df['Ticker'].unique():
                    df_t = df[df['Ticker'] == t]
                    # Asumimos que P/L $ == 0 son las Compras (Entradas) y != 0 son Ventas (Salidas)
                    compras = df_t[df_t['P/L $'] == 0]['Acciones'].sum()
                    ventas = df_t[df_t['P/L $'] != 0]['Acciones'].sum()
                    abiertas = compras - ventas
                    
                    if abiertas > 0:
                        # Buscamos el precio de entrada promedio de esas acciones
                        compras_df = df_t[df_t['P/L $'] == 0]
                        px_promedio = (compras_df['Acciones'] * compras_df['Precio Entrada']).sum() / compras if compras > 0 else 0
                        
                        portafolio[t] = {
                            "Acciones": int(abiertas),
                            "Precio Promedio": px_promedio
                        }
                
                if portafolio:
                    # Dibujamos las tarjetas del portafolio
                    for t, data in portafolio.items():
                        st.info(f"**{t}** | 📦 {formato_entero(data['Acciones'])} acciones abiertas | 🎯 P. Promedio: ${formato_es(data['Precio Promedio'])}")
                    
                    st.markdown("##### ✂️ Registrar Salida (Scaling Out)")
                    with st.form("form_cerrar_trade", clear_on_submit=True):
                        t_salida = st.selectbox("Selecciona la posición a gestionar:", list(portafolio.keys()))
                        col_s1, col_s2 = st.columns(2)
                        with col_s1:
                            f_salida = st.date_input("Fecha de Salida")
                            a_salida = st.number_input("Acciones a Vender", min_value=1, step=1)
                        with col_s2:
                            p_salida = st.number_input("Precio de Venta ($)", min_value=0.01, step=0.01)
                            n_salida = st.text_input("Notas de Venta")
                            
                        btn_cerrar = st.form_submit_button("💰 Ejecutar Salida")
                        
                        if btn_cerrar:
                            if a_salida > portafolio[t_salida]["Acciones"]:
                                st.error("⚠️ No puedes vender más acciones de las que tienes abiertas en el portafolio.")
                            elif p_salida <= 0:
                                st.error("⚠️ Precio de venta inválido.")
                            else:
                                px_ent = portafolio[t_salida]["Precio Promedio"]
                                monto_s = a_salida * px_ent
                                pl_usd = (p_salida - px_ent) * a_salida
                                pl_pct = ((p_salida - px_ent) / px_ent) * 100
                                
                                fila_salida = [str(f_salida), t_salida, a_salida, px_ent, monto_s, p_salida, round(pl_pct, 2), round(pl_usd, 2), n_salida, usuario_actual]
                                
                                try:
                                    sheet.append_row(fila_salida)
                                    st.success(f"¡Venta registrada! Liquidaste {a_salida} acciones de {t_salida}. Presiona **F5** para actualizar.")
                                except Exception as e:
                                    st.error(f"Error al guardar: {e}")
                else:
                    st.success("Tus manos están libres. No tienes operaciones abiertas actualmente. ¡Busca el próximo setup! 🦅")

# ==========================================
# PESTAÑA 3: MÉTRICAS (Dashboard Avanzado)
# ==========================================
with tab_dash:
    st.subheader("📊 Métricas de Rendimiento y Análisis") 
    
    st.markdown("##### ⚙️ Configuración y Filtros")
    f_col1, f_col2, f_col3 = st.columns(3)
    
    with f_col1:
        capital_inicial = st.number_input("Capital Inicial ($):", min_value=1.0, value=30000.0, step=1000.0)
    
    if conexion_exitosa and not df.empty:
        df_cerradas = df[df['P/L $'] != 0].copy()
        
        if not df_cerradas.empty:
            df_cerradas['Fecha_DT'] = pd.to_datetime(df_cerradas['Fecha'], errors='coerce', format='mixed')
            
            # --- FILTROS DINÁMICOS ---
            tickers_unicos = ["TODOS"] + sorted(df_cerradas['Ticker'].unique().tolist())
            with f_col2:
                ticker_filtro = st.selectbox("Filtrar por Ticker:", tickers_unicos)
            
            with f_col3:
                fechas_min = df_cerradas['Fecha_DT'].min().date()
                fechas_max = df_cerradas['Fecha_DT'].max().date()
                rango_fechas = st.date_input("Rango de Fechas:", [fechas_min, fechas_max])
            
            st.write("---")
            
            # --- APLICAR FILTROS ---
            df_filtrado = df_cerradas.copy()
            if ticker_filtro != "TODOS":
                df_filtrado = df_filtrado[df_filtrado['Ticker'] == ticker_filtro]
            
            if len(rango_fechas) == 2:
                start_date, end_date = rango_fechas
                df_filtrado = df_filtrado[(df_filtrado['Fecha_DT'].dt.date >= start_date) & (df_filtrado['Fecha_DT'].dt.date <= end_date)]
            
            if not df_filtrado.empty:
                # Cálculos con la data filtrada
                ganadoras = df_filtrado[df_filtrado['P/L $'] > 0]
                perdedoras = df_filtrado[df_filtrado['P/L $'] < 0]
                
                total_trades = len(df_filtrado)
                win_rate = (len(ganadoras) / total_trades) * 100
                
                avg_win = ganadoras['P/L $'].mean() if not ganadoras.empty else 0
                avg_loss = abs(perdedoras['P/L $'].mean()) if not perdedoras.empty else 0
                
                gross_profit = ganadoras['P/L $'].sum()
                gross_loss = abs(perdedoras['P/L $'].sum())
                profit_factor = gross_profit / gross_loss if gross_loss > 0 else gross_profit
                
                pl_neto = df_filtrado['P/L $'].sum()
                
                rentabilidad_historica = (pl_neto / capital_inicial) * 100
                
                año_actual = pd.Timestamp.now().year
                df_anual = df_filtrado[df_filtrado['Fecha_DT'].dt.year == año_actual]
                pl_neto_anual = df_anual['P/L $'].sum()
                rentabilidad_anual = (pl_neto_anual / capital_inicial) * 100
                
                # --- MOSTRAR KPIs ---
                st.markdown("#### Métricas Clave")
                win_rate_str = f"{win_rate:.1f}".replace(".", ",")
                pf_str = formato_es(profit_factor)
                rent_hist_str = f"{rentabilidad_historica:.2f}".replace(".", ",")
                rent_anual_str = f"{rentabilidad_anual:.2f}".replace(".", ",")
                
                r1, r2, r3 = st.columns(3)
                r1.metric("Rentabilidad Histórica", f"{rent_hist_str}%")
                r2.metric(f"Rentabilidad Anual ({año_actual})", f"{rent_anual_str}%")
                r3.metric("P/L Neto de la Selección", f"${formato_es(pl_neto)}")
                
                st.write("") 
                
                k1, k2, k3, k4 = st.columns(4)
                k1.metric("Win Rate", f"{win_rate_str}%")
                k2.metric("Profit Factor", pf_str)
                k3.metric("Avg Win", f"${formato_es(avg_win)}")
                k4.metric("Avg Loss", f"${formato_es(avg_loss)}")
                
                st.write("---")
                
                # --- GRÁFICO DE LÍNEAS TIPO TRADINGVIEW ---
                st.markdown("#### 📈 Curva de Equidad")
                df_filtrado = df_filtrado.sort_values(by='Fecha_DT')
                df_filtrado['Balance de Cuenta'] = capital_inicial + df_filtrado['P/L $'].cumsum()
                
                chart = alt.Chart(df_filtrado).mark_line(
                    color='#2962ff', 
                    strokeWidth=2.5,
                    point=alt.OverlayMarkDef(color='#2962ff', size=60, filled=True)
                ).encode(
                    x=alt.X('Fecha_DT:T', 
                            title='', 
                            axis=alt.Axis(format='%d-%m-%Y', labelAngle=-45, tickCount='month', grid=True)),
                    y=alt.Y('Balance de Cuenta:Q', 
                            title='Equidad ($)',
                            scale=alt.Scale(zero=False)),
                    tooltip=[alt.Tooltip('Fecha_DT:T', title='Fecha', format='%d-%m-%Y'), 
                             alt.Tooltip('Balance de Cuenta:Q', title='Capital', format='$,.2f')]
                ).properties(height=400).interactive()
                
                st.altair_chart(chart, use_container_width=True)
                
                st.write("---")
                
                # --- TABLA DE HISTORIAL ---
                st.markdown("#### 📋 Historial de Operaciones Cerradas")
                columnas_mostrar = ['Fecha', 'Ticker', 'Acciones', 'Precio Entrada', 'Precio Salida', 'P/L %', 'P/L $', 'Notas']
                df_mostrar = df_filtrado[columnas_mostrar].copy()
                
                df_mostrar['Precio Entrada'] = df_mostrar['Precio Entrada'].apply(lambda x: f"${formato_es(x)}")
                df_mostrar['Precio Salida'] = df_mostrar['Precio Salida'].apply(lambda x: f"${formato_es(x)}")
                df_mostrar['P/L %'] = df_mostrar['P/L %'].apply(lambda x: f"{formato_es(x)}%")
                df_mostrar['P/L $'] = df_mostrar['P/L $'].apply(lambda x: f"${formato_es(x)}")
                
                st.dataframe(df_mostrar, width='stretch', hide_index=True)
                
            else:
                st.warning("⚠️ No hay operaciones que coincidan con los filtros seleccionados.")
        else:
            st.info("💡 Aún no hay operaciones cerradas registradas para calcular métricas.")
    else:
        st.warning("⚠️ No hay datos en la base de datos o revisa tu conexión.")

        # --- 🗑️ SECCIÓN: ELIMINAR OPERACIÓN (MÉTRICAS) ---
    st.write("---")
    st.markdown("### ⚙️ Administración de Datos")
    with st.expander("🗑️ Eliminar un registro de la base de datos"):
        st.warning("⚠️ Cuidado: Al eliminar un registro, se borrará definitivamente de la base de datos.")
        
        # Leemos la hoja completa
        df_eliminar = pd.DataFrame(sheet.get_all_records())
        
        if not df_eliminar.empty:
            # La fila 1 son los títulos, la data empieza en la 2
            df_eliminar['Fila_Excel'] = df_eliminar.index + 2
            
            # SOLUCIÓN BLINDADA: Tomamos las columnas por su orden (0, 1 y 2) ignorando sus nombres
            col_1 = df_eliminar.columns[0] # Usualmente Fecha
            col_2 = df_eliminar.columns[1] # Usualmente Ticker
            col_3 = df_eliminar.columns[2] # Usualmente Acciones
            
            df_eliminar['Etiqueta'] = df_eliminar[col_1].astype(str) + " | " + df_eliminar[col_2].astype(str) + " | Acciones: " + df_eliminar[col_3].astype(str)
            
            opciones_borrar = dict(zip(df_eliminar['Etiqueta'], df_eliminar['Fila_Excel']))
            
            trade_a_borrar = st.selectbox("Selecciona la operación que deseas eliminar:", options=[""] + list(opciones_borrar.keys()))
            
            if st.button("🗑️ Eliminar Definitivamente"):
                if trade_a_borrar != "":
                    fila_exacta = opciones_borrar[trade_a_borrar]
                    sheet.delete_rows(int(fila_exacta))
                    st.success(f"✅ Registro eliminado con éxito.")
                    st.rerun()
                else:
                    st.error("⚠️ Por favor, selecciona una operación de la lista.")
        else:
            st.info("No hay operaciones registradas para eliminar.")