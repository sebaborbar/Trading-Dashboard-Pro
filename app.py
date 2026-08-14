import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import math
import altair as alt
from io import StringIO
import csv

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
                usuarios_autorizados = dict(st.secrets["usuarios"])
                if usuario in usuarios_autorizados and usuarios_autorizados[usuario] == password:
                    st.session_state['logeado'] = True
                    st.session_state['usuario_actual'] = usuario
                    st.rerun()
                else:
                    st.error("⚠️ Usuario o contraseña incorrectos.")
    st.stop()

# --- SI EL LOGIN ES EXITOSO, LA APP CONTINÚA AQUÍ ---
usuario_actual = st.session_state['usuario_actual']

st.sidebar.title("👤 Perfil")
st.sidebar.success(f"🟢 Sesión activa: {usuario_actual}")
if st.sidebar.button("🚪 Cerrar Sesión"):
    st.session_state['logeado'] = False
    st.rerun()
if st.sidebar.button("🔄 Actualizar Bóveda"):
    st.rerun()

st.title(f"📈 TRADING DASHBOARD | {usuario_actual}")
st.write("---")

# --- FUNCIONES AUXILIARES ---
def formato_es(num):
    return f"{num:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def formato_entero(num):
    return f"{num:,}".replace(",", ".")

def parse_money(x):
    """Convierte a float sin importar si Google Sheets lo formateó con coma
    decimal (109,99), punto decimal (109.99), o formato europeo (1.234,56).
    Sheets reformatea números automáticamente según el idioma de la hoja,
    así que cualquier valor numérico leído de vuelta debe pasar por acá."""
    if pd.isna(x): return 0.0
    x = str(x).replace('$', '').replace('%', '').strip()
    if not x: return 0.0
    if '.' in x and ',' in x:
        if x.rfind(',') > x.rfind('.'):
            x = x.replace('.', '').replace(',', '.')
        else:
            x = x.replace(',', '')
    elif ',' in x:
        x = x.replace(',', '.')
    try:
        return float(x)
    except ValueError:
        return 0.0

# --- 2. CONEXIÓN A GOOGLE SHEETS ---
capital_base_guardado = None
fecha_base_guardada = None

try:
    import json
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    info_cuenta = json.loads(st.secrets["google_json"])
    creds = Credentials.from_service_account_info(info_cuenta, scopes=scopes)
    client = gspread.authorize(creds)
    spreadsheet = client.open("DB_Trading_App")
    sheet = spreadsheet.worksheet("journal")

    # Hoja "config": guarda el Capital Base + Fecha Base por usuario
    nombres_hojas = [ws.title for ws in spreadsheet.worksheets()]
    if "config" in nombres_hojas:
        sheet_config = spreadsheet.worksheet("config")
    else:
        sheet_config = spreadsheet.add_worksheet(title="config", rows=200, cols=3)
        sheet_config.append_row(["Usuario", "CapitalBase", "FechaBase"])

    filas_config = sheet_config.get_all_values()
    if len(filas_config) > 1:
        df_config = pd.DataFrame(filas_config[1:], columns=filas_config[0])
        fila_usuario_config = df_config[df_config["Usuario"] == usuario_actual]
        if not fila_usuario_config.empty:
            try:
                capital_base_guardado = float(str(fila_usuario_config.iloc[0]["CapitalBase"]).replace(",", "."))
                fecha_base_guardada = pd.to_datetime(fila_usuario_config.iloc[0]["FechaBase"]).date()
            except (ValueError, TypeError):
                capital_base_guardado = None
                fecha_base_guardada = None

    # Hoja "movimientos": depósitos y retiros de capital por usuario
    if "movimientos" in nombres_hojas:
        sheet_movimientos = spreadsheet.worksheet("movimientos")
    else:
        sheet_movimientos = spreadsheet.add_worksheet(title="movimientos", rows=500, cols=4)
        sheet_movimientos.append_row(["Usuario", "Fecha", "Monto", "Nota"])

    # Hoja "posiciones": snapshot de Open Positions de IBKR por usuario.
    # A diferencia de journal/movimientos, esto NO se acumula — cada import
    # la reemplaza completa, porque es una foto del momento, no un historial.
    COLS_POSICIONES = ["Usuario", "Symbol", "Side", "Quantity", "CostBasisPrice",
                        "MarkPrice", "PositionValue", "UnrealizedPL", "ReportDate"]
    if "posiciones" in nombres_hojas:
        sheet_posiciones = spreadsheet.worksheet("posiciones")
    else:
        sheet_posiciones = spreadsheet.add_worksheet(title="posiciones", rows=200, cols=len(COLS_POSICIONES))
        sheet_posiciones.append_row(COLS_POSICIONES)

    # --- MIGRACIÓN AUTOMÁTICA DE ESQUEMA ---
    # Agrega columnas nuevas a hojas ya existentes, sin tocar los datos que ya tienen.
    header_journal = sheet.row_values(1)
    if "TradeID" not in header_journal:
        if sheet.col_count < len(header_journal) + 1:
            sheet.add_cols(1)
        sheet.update_cell(1, len(header_journal) + 1, "TradeID")

    header_mov = sheet_movimientos.row_values(1)
    if "TransactionID" not in header_mov:
        if sheet_movimientos.col_count < len(header_mov) + 1:
            sheet_movimientos.add_cols(1)
        sheet_movimientos.update_cell(1, len(header_mov) + 1, "TransactionID")

    conexion_exitosa = True

    filas = sheet.get_all_values()
    if len(filas) > 1:
        df = pd.DataFrame(filas[1:], columns=filas[0])
        df.columns = df.columns.str.strip()

        cols_numericas = ['Acciones', 'Precio Entrada', 'Precio Salida', 'P/L %', 'P/L $']
        for col in cols_numericas:
            if col in df.columns:
                df[col] = df[col].apply(parse_money)
    else:
        df = pd.DataFrame()

except Exception as e:
    conexion_exitosa = False
    df = pd.DataFrame()
    st.sidebar.error(f"Error de base de datos: {e}")

# 🔒 GUARDIÁN DE PRIVACIDAD
if 'Usuario' in df.columns:
    df = df[df['Usuario'] == usuario_actual]

# --- CARGAR MOVIMIENTOS DE CAPITAL (depósitos/retiros) DEL USUARIO ---
df_movimientos = pd.DataFrame()
if conexion_exitosa:
    try:
        filas_mov = sheet_movimientos.get_all_values()
        if len(filas_mov) > 1:
            df_movimientos = pd.DataFrame(filas_mov[1:], columns=filas_mov[0])
            df_movimientos = df_movimientos[df_movimientos['Usuario'] == usuario_actual].copy()
            if not df_movimientos.empty:
                df_movimientos['Monto']    = df_movimientos['Monto'].apply(parse_money)
                df_movimientos['Fecha_DT'] = pd.to_datetime(df_movimientos['Fecha'], errors='coerce', format='mixed')
                df_movimientos = df_movimientos.dropna(subset=['Fecha_DT'])
    except Exception:
        df_movimientos = pd.DataFrame()

# --- CARGAR SNAPSHOT DE POSICIONES ABIERTAS (Open Positions de IBKR) ---
df_posiciones = pd.DataFrame()
if conexion_exitosa:
    try:
        filas_pos = sheet_posiciones.get_all_values()
        if len(filas_pos) > 1:
            df_posiciones = pd.DataFrame(filas_pos[1:], columns=filas_pos[0])
            df_posiciones = df_posiciones[df_posiciones['Usuario'] == usuario_actual].copy()
            if not df_posiciones.empty:
                for col_num in ["Quantity", "CostBasisPrice", "MarkPrice", "PositionValue", "UnrealizedPL"]:
                    df_posiciones[col_num] = df_posiciones[col_num].apply(parse_money)
    except Exception:
        df_posiciones = pd.DataFrame()

# --- 3. MENÚ DE NAVEGACIÓN ---
tab_calc, tab_bitacora, tab_dash = st.tabs([
    "🧮 Calculadora de Riesgo",
    "📝 Bitácora",
    "📊 Métricas de Rendimiento"
])

# ==========================================
# INICIALIZACIÓN DE SESSION STATE
# ==========================================
if 'registro_calculos' not in st.session_state:
    st.session_state['registro_calculos'] = []

if 'prefill_bitacora' not in st.session_state:
    st.session_state['prefill_bitacora'] = None

# ==========================================
# PESTAÑA 1: CALCULADORA DE RIESGO
# ==========================================
with tab_calc:
    st.subheader("⚙️ Configuración del Trade")
    direccion = st.radio("Dirección del Trade:", ["ALZA 🟢 (Long)", "BAJA 🔴 (Short)"], horizontal=True)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**1. Datos del Capital**")
        capital = st.number_input("Capital Total ($)", min_value=0.0, value=30000.0, step=1000.0)
        st.caption(f"💰 {formato_es(capital)}")
        riesgo_pct = st.number_input("Riesgo (%)", min_value=0.1, value=0.50, step=0.1)
        riesgo_usd = capital * (riesgo_pct / 100)
        st.info(f"**Riesgo en dinero:** ${formato_es(riesgo_usd)}")

    with col2:
        st.markdown("**2. Datos del Gráfico**")
        ticker = st.text_input("TICKER", value="AAAA").upper()
        breakout = st.number_input("Precio Breakout/Breakdown ($)", min_value=0.0, value=50.0, step=0.5)
        atr = st.number_input("ATR ($)", min_value=0.0, value=4.89, step=0.1)
        if "ALZA" in direccion:
            extremo = st.number_input("Precio Último Mínimo ($)", min_value=0.0, value=46.0, step=0.5)
        else:
            extremo = st.number_input("Precio Último Máximo ($)", min_value=0.0, value=54.0, step=0.5)

    st.markdown("**3. Objetivo de Ganancia**")
    rr_ratio = st.select_slider(
        "Ratio Riesgo/Recompensa:",
        options=[1.5, 2.0, 2.5, 3.0, 3.5, 4.0],
        value=2.0,
        format_func=lambda x: f"{x}:1"
    )

    st.write("---")
    
    if breakout > 0 and extremo > 0:
        if "ALZA" in direccion:
            entrada = breakout * 1.001
            sl_extremo = extremo * 0.995
            sl_atr = breakout - atr
            sl_definitivo = min(sl_extremo, sl_atr)
            condicion_valida = entrada > sl_definitivo and sl_definitivo > 0
        else:
            entrada = breakout * 0.999
            sl_extremo = extremo * 1.005
            sl_atr = breakout + atr
            sl_definitivo = max(sl_extremo, sl_atr)
            condicion_valida = sl_definitivo > entrada and entrada > 0

        if condicion_valida:
            if "ALZA" in direccion:
                riesgo_por_accion = entrada - sl_definitivo
                texto_accion = "COMPRAR"
                texto_salida = "VENDER"
            else:
                riesgo_por_accion = sl_definitivo - entrada
                texto_accion = "VENDER EN CORTO"
                texto_salida = "COMPRAR PARA CUBRIR"

            acciones_a_comprar = math.floor(riesgo_usd / riesgo_por_accion)
            monto_exposicion = acciones_a_comprar * entrada
            acciones_vender_tp = math.ceil(acciones_a_comprar / 2)
            take_profit = entrada + (riesgo_por_accion * rr_ratio) if "ALZA" in direccion else entrada - (riesgo_por_accion * rr_ratio)

            acc_str = formato_entero(acciones_a_comprar)
            acc_tp_str = formato_entero(acciones_vender_tp)

            st.subheader("Plan de Acción")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Acciones", acc_str)
            c2.metric("Entrada", f"${formato_es(entrada)}")
            c3.metric("Stop Loss", f"${formato_es(sl_definitivo)}")
            c4.metric(f"Take Profit ({rr_ratio}:1)", f"${formato_es(take_profit)}")

            st.warning(
                f"**💡 Resumen de Ejecución:**\n\n"
                f"Debes **{texto_accion} {acc_str} acciones** de **{ticker}** a **${formato_es(entrada)}**.\n\n"
                f"Tu exposición total será de **${formato_es(monto_exposicion)}**.\n\n"
                f"Al llegar a tu objetivo, debes **{texto_salida} {acc_tp_str} acciones** para asegurar tu ganancia."
            )

            st.write("---")
            col_btn1, col_btn2 = st.columns(2)

            with col_btn1:
                if st.button("💾 Guardar en Registro del Día"):
                    if len(st.session_state['registro_calculos']) >= 4:
                        st.warning("⚠️ Ya tienes 4 cálculos guardados. Borra uno para continuar.")
                    else:
                        nuevo_calculo = {
                            'ticker': ticker,
                            'direccion': "ALZA 🟢" if "ALZA" in direccion else "BAJA 🔴",
                            'acciones': acciones_a_comprar,
                            'entrada': entrada,
                            'sl': sl_definitivo,
                            'tp': take_profit,
                            'rr': rr_ratio,
                            'exposicion': monto_exposicion
                        }
                        st.session_state['registro_calculos'].append(nuevo_calculo)
                        st.success(f"✅ {ticker} guardado en el registro del día.")

            with col_btn2:
                if st.button("📋 Enviar a Bitácora"):
                    st.session_state['prefill_bitacora'] = {
                        'ticker': ticker,
                        'acciones': acciones_a_comprar,
                        'precio': round(entrada, 2)
                    }
                    st.session_state["selector_modo"] = "🟢 Gestión en Vivo (Portafolio)"
                    st.success("✅ Datos enviados. Ve a la pestaña **Bitácora** para confirmar la entrada.")
        else:
            st.error("🚨 Datos inválidos: Para ALZA, el Mínimo debe ser menor al Breakout. Para BAJA, el Máximo debe ser mayor al Breakout.")

    st.write("---")
    st.markdown("#### 🗂️ Registro del Día")

    if st.session_state['registro_calculos']:
        for i, calc in enumerate(st.session_state['registro_calculos']):
            with st.expander(f"#{i+1} — {calc['ticker']} | {calc['direccion']} | Entrada: ${formato_es(calc['entrada'])} | TP {calc['rr']}:1"):
                r1, r2, r3, r4, r5 = st.columns(5)
                r1.metric("Acciones", formato_entero(calc['acciones']))
                r2.metric("Entrada", f"${formato_es(calc['entrada'])}")
                r3.metric("Stop Loss", f"${formato_es(calc['sl'])}")
                r4.metric("Take Profit", f"${formato_es(calc['tp'])}")
                r5.metric("Exposición", f"${formato_es(calc['exposicion'])}")
                if st.button(f"🗑️ Borrar #{i+1}", key=f"borrar_{i}"):
                    st.session_state['registro_calculos'].pop(i)
                    st.rerun()
    else:
        st.info("No hay cálculos guardados hoy. Usa el botón **💾 Guardar en Registro del Día** para añadir hasta 4 planes de trading.")

# ==========================================
# PESTAÑA 2: BITÁCORA
# ==========================================
with tab_bitacora:
    if "selector_modo" not in st.session_state:
        st.session_state["selector_modo"] = "🟢 Gestión en Vivo (Portafolio)"

    modo_bitacora = st.radio(
        "🎛️ Selecciona tu modo de trabajo:",
        ["◀️ Registro Histórico", "🟢 Gestión en Vivo (Portafolio)", "📥 Importar desde IBKR"],
        horizontal=True,
        key="selector_modo"
    )
    st.write("---")

    # ------------------------------------------
    # MODO 1: REGISTRO HISTÓRICO
    # ------------------------------------------
    if modo_bitacora == "◀️ Registro Histórico":
        st.subheader("📄 Registro Histórico")
        st.markdown("Ideal para subir trades antiguos.")

        with st.expander("⚙️ Configurar Capital Base (punto de partida para Métricas)", expanded=(capital_base_guardado is None)):
            st.caption(
                "Define la fecha y el capital con el que empezaste a operar bajo este sistema. "
                "El 'Capital Inicial' de la pestaña Métricas de Rendimiento se recalculará solo "
                "a partir de este punto cada vez que cambies el rango de fechas."
            )
            cb1, cb2 = st.columns(2)
            with cb1:
                nueva_fecha_base = st.date_input(
                    "Fecha de inicio",
                    value=fecha_base_guardada if fecha_base_guardada else pd.Timestamp.now().date(),
                    format="DD/MM/YYYY",
                    key="input_fecha_base"
                )
            with cb2:
                nuevo_capital_base = st.number_input(
                    "Capital base ($)",
                    min_value=0.0,
                    value=float(capital_base_guardado) if capital_base_guardado is not None else 30000.0,
                    step=1000.0,
                    key="input_capital_base"
                )
            if st.button("💾 Guardar Capital Base"):
                try:
                    filas_config_actual = sheet_config.get_all_values()
                    fila_encontrada = None
                    for idx, fila in enumerate(filas_config_actual[1:], start=2):
                        if fila and fila[0] == usuario_actual:
                            fila_encontrada = idx
                            break
                    valores_nuevos = [usuario_actual, nuevo_capital_base, str(nueva_fecha_base)]
                    if fila_encontrada:
                        sheet_config.update(f"A{fila_encontrada}:C{fila_encontrada}", [valores_nuevos])
                    else:
                        sheet_config.append_row(valores_nuevos)
                    st.success("✅ Capital base guardado. Ve a **Métricas de Rendimiento** para verlo aplicado.")
                except Exception as e:
                    st.error(f"Error al guardar el capital base: {e}")

        with st.expander("💵 Movimientos de Capital (Depósitos / Retiros)"):
            st.caption(
                "Registra cada depósito o retiro que hagas de tu cuenta de trading. "
                "Esto ajusta el Capital Inicial/Final de Métricas para que coincida con IBKR."
            )
            mv1, mv2, mv3 = st.columns([1, 1, 1])
            with mv1:
                fecha_mov = st.date_input("Fecha del movimiento", format="DD/MM/YYYY", key="fecha_mov")
            with mv2:
                tipo_mov = st.radio("Tipo", ["Depósito ➕", "Retiro ➖"], key="tipo_mov", horizontal=True)
            with mv3:
                monto_mov = st.number_input("Monto ($)", min_value=0.0, step=100.0, key="monto_mov")
            nota_mov = st.text_input("Nota (opcional)", key="nota_mov")

            if st.button("💾 Guardar Movimiento"):
                if monto_mov <= 0:
                    st.warning("⚠️ Ingresa un monto mayor a cero.")
                else:
                    monto_firmado = monto_mov if "Depósito" in tipo_mov else -monto_mov
                    try:
                        sheet_movimientos.append_row([usuario_actual, str(fecha_mov), monto_firmado, nota_mov, ""])
                        st.success("✅ Movimiento guardado. Actualiza la bóveda para verlo reflejado.")
                    except Exception as e:
                        st.error(f"Error al guardar el movimiento: {e}")

            if not df_movimientos.empty:
                st.markdown("###### Movimientos registrados")
                df_mov_mostrar = df_movimientos.sort_values('Fecha_DT').copy()
                df_mov_mostrar['Fecha']  = df_mov_mostrar['Fecha_DT'].dt.strftime('%d/%m/%Y')
                df_mov_mostrar['Monto']  = df_mov_mostrar['Monto'].apply(lambda x: f"${formato_es(x)}")
                st.dataframe(df_mov_mostrar[['Fecha', 'Monto', 'Nota']], hide_index=True, use_container_width=True)

                etiquetas_mov = {
                    f"{row['Fecha_DT'].strftime('%d/%m/%Y')} | ${formato_es(row['Monto'])} | {row.get('Nota', '')}": idx
                    for idx, row in df_movimientos.sort_values('Fecha_DT').iterrows()
                }
                mov_a_borrar = st.selectbox(
                    "Selecciona un movimiento para eliminar:",
                    options=[""] + list(etiquetas_mov.keys()),
                    key="selector_borrar_mov"
                )
                if st.button("🗑️ Eliminar Movimiento"):
                    if mov_a_borrar != "":
                        try:
                            filas_mov_actual = sheet_movimientos.get_all_values()
                            fila_a_borrar = None
                            for idx, fila in enumerate(filas_mov_actual[1:], start=2):
                                if (len(fila) >= 4 and fila[0] == usuario_actual
                                        and fila[1] == str(df_movimientos.loc[etiquetas_mov[mov_a_borrar], 'Fecha'])
                                        and fila[2] == str(df_movimientos.loc[etiquetas_mov[mov_a_borrar], 'Monto'])):
                                    fila_a_borrar = idx
                                    break
                            if fila_a_borrar:
                                sheet_movimientos.delete_rows(fila_a_borrar)
                                st.success("✅ Movimiento eliminado.")
                                st.rerun()
                            else:
                                st.error("No se encontró el movimiento exacto en la hoja. Bórralo manualmente en Google Sheets.")
                        except Exception as e:
                            st.error(f"Error al eliminar: {e}")
                    else:
                        st.error("⚠️ Selecciona un movimiento de la lista.")

        with st.form("form_trade_avanzado", clear_on_submit=True):
            st.markdown("#### 1. Datos de Entrada")
            col1, col2, col3, col4 = st.columns(4)
            with col1: fecha_entrada = st.date_input("Fecha de Entrada", format="DD/MM/YYYY")
            with col2: ticker_form = st.text_input("Ticker (Ej: NVDA)").upper()
            with col3: acciones_totales = st.number_input("Total Acciones", step=1)
            with col4: precio_entrada_form = st.number_input("Precio Entrada ($)", step=0.50)

            notas_entrada = st.text_input("Notas de Entrada")
            st.markdown("---")

            st.markdown("#### 2. Salidas Parciales")
            s1_c1, s1_c2, s1_c3, s1_c4 = st.columns(4)
            with s1_c1: fecha_s1 = st.date_input("Fecha Salida 1", key="f1", format="DD/MM/YYYY")
            with s1_c2: acc_s1 = st.number_input("Cantidad de Acciones", step=1, key="a1")
            with s1_c3: precio_s1 = st.number_input("Precio Salida ($)", step=0.5, key="p1")
            with s1_c4: notas_s1 = st.text_input("Notas Salida 1", key="n1")

            s2_c1, s2_c2, s2_c3, s2_c4 = st.columns(4)
            with s2_c1: fecha_s2 = st.date_input("Fecha Salida 2", key="f2", format="DD/MM/YYYY")
            with s2_c2: acc_s2 = st.number_input("Cantidad de Acciones", step=1, key="a2")
            with s2_c3: precio_s2 = st.number_input("Precio Salida ($)", step=0.5, key="p2")
            with s2_c4: notas_s2 = st.text_input("Notas Salida 2", key="n2")

            s3_c1, s3_c2, s3_c3, s3_c4 = st.columns(4)
            with s3_c1: fecha_s3 = st.date_input("Fecha Salida 3", key="f3", format="DD/MM/YYYY")
            with s3_c2: acc_s3 = st.number_input("Cantidad de Acciones", step=1, key="a3")
            with s3_c3: precio_s3 = st.number_input("Precio Salida ($)", step=0.5, key="p3")
            with s3_c4: notas_s3 = st.text_input("Notas Salida 3", key="n3")

            st.write("---")
            submit_button = st.form_submit_button("💾 Guardar Historial en Base de Datos")

        if submit_button:
            if ticker_form == "" or precio_entrada_form <= 0 or acciones_totales == 0:
                st.warning("⚠️ Ingresa un Ticker, acciones (no puede ser cero) y precio válidos.")
            elif abs(acc_s1 + acc_s2 + acc_s3) > abs(acciones_totales):
                st.error("⚠️ Error: Ingresaste más salidas parciales que el tamaño de tu posición original.")
            else:
                filas_a_guardar = []
                monto_entrada = acciones_totales * precio_entrada_form
                filas_a_guardar.append([str(fecha_entrada), ticker_form, acciones_totales, precio_entrada_form, monto_entrada, 0.0, 0.0, 0.0, notas_entrada, usuario_actual, ""])

                def procesar_salida(f_fecha, f_acc, f_precio, f_notas):
                    if abs(f_acc) > 0 and f_precio > 0:
                        acc_abs = abs(f_acc)
                        monto_salida = acc_abs * f_precio
                        # El signo de la salida es SIEMPRE contrario al de la entrada:
                        # entrada larga (+) se cierra con salida negativa, entrada corta
                        # (-) se cubre con salida positiva. No depende del signo que
                        # haya tipeado el usuario en el campo, solo de su magnitud.
                        signo_entrada = 1 if acciones_totales > 0 else -1
                        acc_salida_signed = -signo_entrada * acc_abs
                        if acciones_totales > 0:
                            pl_usd = (f_precio - precio_entrada_form) * acc_abs
                            pl_pct = ((f_precio - precio_entrada_form) / precio_entrada_form) * 100
                        else:
                            pl_usd = (precio_entrada_form - f_precio) * acc_abs
                            pl_pct = ((precio_entrada_form - f_precio) / precio_entrada_form) * 100
                        return [str(f_fecha), ticker_form, acc_salida_signed, precio_entrada_form, monto_salida, f_precio, round(pl_pct, 2), round(pl_usd, 2), f_notas, usuario_actual, ""]
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

    # ------------------------------------------
    # MODO 2: GESTIÓN EN VIVO
    # ------------------------------------------
    elif modo_bitacora == "🟢 Gestión en Vivo (Portafolio)":
        col_izq, col_der = st.columns([1, 1.2])

        with col_izq:
            st.markdown("#### 🚀 Abrir Nueva Operación")
            st.markdown("Registra tu entrada al mercado aquí.")
            with st.form("form_abrir_trade", clear_on_submit=True):
                prefill = st.session_state.get('prefill_bitacora') or {}
                ticker_default   = prefill.get('ticker', '')
                acciones_default = int(prefill.get('acciones', 0))
                precio_default   = float(prefill.get('precio', 0.01))
                
                f_compra  = st.date_input("Fecha de Compra", format="DD/MM/YYYY")
                t_compra  = st.text_input("Ticker (Ej: TSLA)", value=ticker_default).upper()
                dir_compra = st.radio("Dirección", ["🟢 Largo (Compra)", "🔴 Corto (Venta en descubierto)"], horizontal=True)
                a_compra  = st.number_input("Cantidad de Acciones", min_value=0, step=1, value=abs(acciones_default))
                p_compra  = st.number_input("Precio de Compra ($)", min_value=0.01, step=0.01, value=precio_default)
                n_compra  = st.text_input("Notas Iniciales (Ej: Entrada Power Kick)")
                
                btn_abrir = st.form_submit_button("🛒 Entrar al Mercado")
                if btn_abrir:
                    if t_compra != "" and p_compra > 0 and a_compra > 0:
                        signo_compra    = 1 if "Largo" in dir_compra else -1
                        a_compra_signed = signo_compra * a_compra
                        monto = a_compra * p_compra
                        fila = [str(f_compra), t_compra, a_compra_signed, p_compra, monto, 0.0, 0.0, 0.0, n_compra, usuario_actual, ""]
                        try:
                            sheet.append_row(fila)
                            st.session_state['prefill_bitacora'] = None
                            st.success(f"¡Posición abierta! Haz clic en **Actualizar Bóveda** para ver a {t_compra}.")
                        except Exception as e:
                            st.error(f"Error: {e}")
                    else:
                        st.warning("⚠️ Revisa el Ticker, la cantidad y el precio.")

        with col_der:
            st.markdown("#### 💼 Portafolio Activo")
            portafolio = {}
            usando_snapshot_ibkr = conexion_exitosa and not df_posiciones.empty

            if usando_snapshot_ibkr:
                # Fuente autoritativa: la foto de Open Positions de IBKR, no una
                # reconstrucción desde el historial de Trades — inmune a huecos
                # de fechas en los archivos que hayas importado.
                for _, row in df_posiciones.iterrows():
                    portafolio[row['Symbol']] = {
                        'Acciones': row['Quantity'],
                        'Precio Promedio': round(row['CostBasisPrice'], 2),
                        'Monto ($)': round(abs(row['PositionValue']), 2),
                        'P/L No Realizado': round(row['UnrealizedPL'], 2),
                    }
            elif conexion_exitosa and not df.empty:
                # Respaldo: reconstrucción desde el historial de Trades, solo para
                # usuarios que nunca importaron un snapshot de Open Positions
                # (ej. alguien que solo usa Gestión en Vivo manual).
                for t in df['Ticker'].unique():
                    df_t = df[df['Ticker'] == t]
                    tenencia_neta = df_t['Acciones'].sum()
                    if tenencia_neta != 0:
                        signo_actual = 1 if tenencia_neta > 0 else -1
                        df_entradas = df_t[(df_t['P/L $'] == 0) & (df_t['Acciones'] * signo_actual > 0)]
                        if not df_entradas.empty:
                            precio_promedio = (df_entradas['Acciones'].abs() * df_entradas['Precio Entrada']).sum() / df_entradas['Acciones'].abs().sum()
                        else:
                            precio_promedio = 0.0
                        monto_expuesto  = abs(tenencia_neta) * precio_promedio
                        portafolio[t] = {
                            'Acciones': tenencia_neta,
                            'Precio Promedio': round(precio_promedio, 2),
                            'Monto ($)': round(monto_expuesto, 2)
                        }

            if portafolio:
                df_portafolio = pd.DataFrame.from_dict(portafolio, orient='index').reset_index()
                df_portafolio.rename(columns={'index': 'Ticker'}, inplace=True)
                capital_total = df_portafolio['Monto ($)'].sum()

                if usando_snapshot_ibkr:
                    fecha_reporte = str(df_posiciones['ReportDate'].iloc[0]) if 'ReportDate' in df_posiciones.columns else ""
                    fecha_reporte_fmt = fecha_reporte
                    try:
                        fecha_reporte_fmt = pd.to_datetime(fecha_reporte, format="%Y%m%d").strftime("%d/%m/%Y")
                    except Exception:
                        pass
                    st.caption(f"📸 Foto directa de IBKR al {fecha_reporte_fmt}. Para actualizar, vuelve a importar un Flex Query con Open Positions.")
                    pl_no_realizado_total = df_portafolio['P/L No Realizado'].sum()
                    df_portafolio['P/L No Realizado'] = [formato_es(x) for x in df_portafolio['P/L No Realizado']]

                df_portafolio['Precio Promedio'] = [formato_es(x) for x in df_portafolio['Precio Promedio']]
                df_portafolio['Monto ($)']        = [formato_es(x) for x in df_portafolio['Monto ($)']]
                st.dataframe(df_portafolio, hide_index=True, use_container_width=True)
                st.info(f"💰 **Capital Total Expuesto:** ${formato_es(capital_total)}")
                if usando_snapshot_ibkr:
                    color_pl = "🟢" if pl_no_realizado_total >= 0 else "🔴"
                    st.info(f"{color_pl} **P/L No Realizado Total:** ${formato_es(pl_no_realizado_total)}")

                if usando_snapshot_ibkr:
                    st.caption(
                        "ℹ️ Estas posiciones vienen directo de IBKR. Para cerrar una, hazlo en tu bróker "
                        "y luego vuelve a importar el Flex Query — no las cierres manualmente aquí, "
                        "porque el próximo import va a reemplazar este snapshot de todas formas."
                    )
                else:
                    st.markdown("#### 🎯 Registrar Salida")
                    with st.form("form_cerrar_trade", clear_on_submit=True):
                        t_venta = st.selectbox("Selecciona Posición a Cerrar", df_portafolio['Ticker'].tolist())
                        f_venta = st.date_input("Fecha de Salida", format="DD/MM/YYYY")
                        a_venta = st.number_input("Cantidad de Acciones", min_value=0, step=1)
                        p_venta = st.number_input("Precio de Salida ($)", min_value=0.01, step=0.01)
                        n_venta = st.text_input("Notas de Salida")
                        btn_cerrar = st.form_submit_button("🎯 Registrar Salida")
                        
                        if btn_cerrar:
                            max_acc = portafolio[t_venta]['Acciones']
                            if a_venta > 0 and p_venta > 0 and a_venta <= abs(max_acc):
                                p_promedio  = portafolio[t_venta]['Precio Promedio']
                                monto_venta = a_venta * p_venta
                                # El cierre va en el signo CONTRARIO a la posición abierta:
                                # cerrar un largo (max_acc>0) resta, cubrir un corto (max_acc<0) suma.
                                a_venta_signed = -a_venta if max_acc > 0 else a_venta
                                if max_acc > 0:
                                    pl_usd = (p_venta - p_promedio) * a_venta
                                    pl_pct = ((p_venta - p_promedio) / p_promedio) * 100
                                else:
                                    pl_usd = (p_promedio - p_venta) * a_venta
                                    pl_pct = ((p_promedio - p_venta) / p_promedio) * 100
                                fila_salida = [str(f_venta), t_venta, a_venta_signed, p_promedio, monto_venta, p_venta, round(pl_pct, 2), round(pl_usd, 2), n_venta, usuario_actual, ""]
                                try:
                                    sheet.append_row(fila_salida)
                                    resumen = (
                                        f"¡Salida de **{t_venta}** registrada!\n\n"
                                        f"**Ganancia/Pérdida:** ${formato_es(pl_usd)}\n\n"
                                        f"Usa el botón **Actualizar Bóveda** para ver los cambios."
                                    )
                                    if pl_usd >= 0:
                                        st.success(resumen)
                                    else:
                                        st.error(resumen)
                                except Exception as e:
                                    st.error(f"Error al guardar: {e}")
                            else:
                                st.warning(f"⚠️ Revisa los datos. No puedes vender más de {abs(max_acc)} acciones.")
            else:
                st.success("No tienes operaciones abiertas actualmente. ¡Busca el próximo setup! 🎯")

    # ------------------------------------------
    # MODO 3: IMPORTAR DESDE IBKR
    # ------------------------------------------
    else:
        st.subheader("📥 Importar Historial desde Interactive Brokers")
        st.markdown("Sube el CSV exportado desde tu Flex Query de IBKR para cargar operaciones históricas en lote.")

        archivo_ibkr = st.file_uploader("Selecciona el archivo CSV de IBKR", type=["csv"])

        if archivo_ibkr:
            try:
                # --- PARSEO: formato "flat file" de IBKR Flex Query, MULTI-SECCIÓN ---
                # El archivo trae marcadores BOF/BOA/BOS...EOS/EOA/EOF y puede traer
                # más de un bloque BOS/EOS (Trades, Cash Transactions, etc.), cada uno
                # con su propio header. Se enruta cada fila a su sección según el
                # código de sección que viene en la fila BOS (ej. "TRNT"=Trades,
                # "CTRN"=Cash Transactions). Secciones desconocidas se ignoran solas.
                contenido = archivo_ibkr.read().decode("utf-8-sig")
                contenido = contenido.replace('\r\n', '\n').replace('\r', '\n')

                filas_trades = []
                filas_cash   = []
                filas_posiciones = []
                filas_cashreport = []
                seccion_actual = None

                reader = csv.reader(StringIO(contenido))
                for row in reader:
                    if not row:
                        continue
                    primer_campo = row[0].strip()

                    if primer_campo == "BOS":
                        codigo_seccion = row[1].strip() if len(row) > 1 else ""
                        if codigo_seccion == "TRNT":
                            seccion_actual = "TRADES"
                        elif codigo_seccion == "CTRN":
                            seccion_actual = "CASH"
                        elif codigo_seccion == "POST":
                            seccion_actual = "POSICIONES"
                        elif codigo_seccion == "CRTT":
                            seccion_actual = "CASHREPORT"
                        else:
                            seccion_actual = None  # sección no reconocida: se ignora
                        continue

                    if primer_campo in ("BOF", "BOA", "EOF", "EOS", "EOA"):
                        if primer_campo == "EOS":
                            seccion_actual = None
                        continue

                    fila = [c.strip() for c in row]
                    if not any(fila):
                        continue

                    if seccion_actual == "TRADES":
                        filas_trades.append(fila)
                    elif seccion_actual == "CASH":
                        filas_cash.append(fila)
                    elif seccion_actual == "POSICIONES":
                        filas_posiciones.append(fila)
                    elif seccion_actual == "CASHREPORT":
                        filas_cashreport.append(fila)

                if not filas_trades and not filas_cash and not filas_posiciones and not filas_cashreport:
                    st.error("⚠️ No se encontraron datos válidos en el archivo (ni Trades, ni Cash Transactions, ni Open Positions, ni Cash Report).")
                    st.stop()

                # TradeIDs / TransactionIDs ya importados antes (para no duplicar)
                tradeids_existentes = set()
                if 'TradeID' in df.columns:
                    for val in df['TradeID'].dropna():
                        for tid in str(val).split(','):
                            tid = tid.strip()
                            if tid:
                                tradeids_existentes.add(tid)

                transids_existentes = set()
                if not df_movimientos.empty and 'TransactionID' in df_movimientos.columns:
                    transids_existentes = set(
                        str(t).strip() for t in df_movimientos['TransactionID'].dropna() if str(t).strip()
                    )

                filas_finales   = []
                filas_cash_final = []
                filas_posiciones_final = []
                capital_calculado_ibkr = None   # (capital_total, fecha) si viene Cash Report
                advertencias    = []
                trades_omitidos = 0
                cash_omitidos   = 0

                # ============ SECCIÓN TRADES ============
                if filas_trades:
                    header_t = filas_trades[0]
                    df_ibkr = pd.DataFrame(filas_trades[1:], columns=header_t)
                    df_ibkr.columns = df_ibkr.columns.str.strip()

                    cols_requeridas = {"Symbol", "TradeDate", "Quantity", "TradePrice",
                                       "Open/CloseIndicator", "Buy/Sell"}
                    if not cols_requeridas.issubset(set(df_ibkr.columns)):
                        st.error(f"⚠️ Columnas encontradas en Trades: {list(df_ibkr.columns)}")
                        st.stop()

                    tiene_tradeid = "TradeID" in df_ibkr.columns
                    tiene_fifo    = "FifoPnlRealized" in df_ibkr.columns

                    # Omitir ejecuciones ya importadas antes (por TradeID)
                    if tiene_tradeid:
                        filas_previas = len(df_ibkr)
                        df_ibkr = df_ibkr[~df_ibkr["TradeID"].isin(tradeids_existentes)]
                        trades_omitidos = filas_previas - len(df_ibkr)

                    df_ibkr["Quantity"]            = pd.to_numeric(df_ibkr["Quantity"],   errors="coerce")
                    df_ibkr["TradePrice"]          = pd.to_numeric(df_ibkr["TradePrice"], errors="coerce")
                    df_ibkr["TradeDate"]           = pd.to_datetime(df_ibkr["TradeDate"].astype(str), format="%Y%m%d", errors="coerce")
                    if tiene_fifo:
                        df_ibkr["FifoPnlRealized"] = pd.to_numeric(df_ibkr["FifoPnlRealized"], errors="coerce").fillna(0.0)
                    df_ibkr                        = df_ibkr.dropna(subset=["Quantity", "TradePrice", "TradeDate"])
                    df_ibkr["Buy/Sell"]            = df_ibkr["Buy/Sell"].str.strip().str.upper()
                    df_ibkr["Open/CloseIndicator"] = df_ibkr["Open/CloseIndicator"].str.strip().str.upper()

                    if not tiene_tradeid:
                        df_ibkr["TradeID"] = ""

                    # --- CONSOLIDACIÓN por ticker+fecha+dirección+O/C ---
                    df_ibkr["_qty_abs"]  = df_ibkr["Quantity"].abs()
                    df_ibkr["_weighted"] = df_ibkr["_qty_abs"] * df_ibkr["TradePrice"]

                    agg_dict = {
                        "Quantity":     ("Quantity", "sum"),
                        "_qty_abs_sum": ("_qty_abs", "sum"),
                        "_weighted_sum": ("_weighted", "sum"),
                        "TradeIDs":     ("TradeID", lambda s: ",".join(sorted({str(x) for x in s if str(x).strip()}))),
                    }
                    if tiene_fifo:
                        agg_dict["FifoPnlRealized_sum"] = ("FifoPnlRealized", "sum")

                    df_consol = df_ibkr.groupby(
                        ["Symbol", "TradeDate", "Buy/Sell", "Open/CloseIndicator"], as_index=False
                    ).agg(**agg_dict)
                    df_consol["TradePrice"] = (df_consol["_weighted_sum"] / df_consol["_qty_abs_sum"]).round(4)
                    df_consol = df_consol.drop(columns=["_qty_abs_sum", "_weighted_sum"])

                    df_aperturas = df_consol[df_consol["Open/CloseIndicator"] == "O"].copy().sort_values("TradeDate")
                    df_cierres   = df_consol[df_consol["Open/CloseIndicator"] == "C"].copy().sort_values("TradeDate")

                    entradas_ref = {}

                    for _, row in df_aperturas.iterrows():
                        ticker_r    = row["Symbol"]
                        fecha_r     = row["TradeDate"].strftime("%Y-%m-%d")
                        acciones_abs = abs(row["Quantity"])
                        precio_r    = row["TradePrice"]
                        monto_r     = round(acciones_abs * precio_r, 2)

                        # Signo: BUY-to-Open (long) = positivo, SELL-to-Open (corto) = negativo.
                        # Necesario para que "Portafolio Activo" distinga largos de cortos.
                        signo      = 1 if row["Buy/Sell"] == "BUY" else -1
                        acciones_r = signo * acciones_abs

                        clave_prom = (ticker_r, signo)
                        if clave_prom in entradas_ref:
                            prev        = entradas_ref[clave_prom]
                            total_qty   = prev["qty"] + acciones_abs
                            precio_prom = (prev["precio"] * prev["qty"] + precio_r * acciones_abs) / total_qty
                            entradas_ref[clave_prom] = {"precio": round(precio_prom, 4), "qty": total_qty}
                        else:
                            entradas_ref[clave_prom] = {"precio": precio_r, "qty": acciones_abs}

                        filas_finales.append([fecha_r, ticker_r, acciones_r, precio_r, monto_r,
                                              0.0, 0.0, 0.0, "IBKR Import", usuario_actual, row["TradeIDs"]])

                    for _, row in df_cierres.iterrows():
                        ticker_r     = row["Symbol"]
                        fecha_r      = row["TradeDate"].strftime("%Y-%m-%d")
                        acciones_abs = abs(row["Quantity"])
                        precio_sal   = row["TradePrice"]
                        monto_r      = round(acciones_abs * precio_sal, 2)

                        # Un cierre BUY cubre un corto (la apertura fue SELL, signo=-1);
                        # un cierre SELL cierra un largo (la apertura fue BUY, signo=+1).
                        # El cierre en sí queda con el signo CONTRARIO a la apertura que cancela.
                        signo_apertura = -1 if row["Buy/Sell"] == "BUY" else 1
                        clave_prom     = (ticker_r, signo_apertura)
                        acciones_r     = -signo_apertura * acciones_abs

                        if clave_prom in entradas_ref:
                            precio_ent = entradas_ref[clave_prom]["precio"]
                        else:
                            precio_ent = precio_sal
                            advertencias.append(ticker_r)

                        if tiene_fifo:
                            # P/L exacto de IBKR (FIFO real, comisión ya descontada)
                            pl_usd = round(row["FifoPnlRealized_sum"], 2)
                            pl_pct = round((pl_usd / (precio_ent * acciones_abs)) * 100, 2) if precio_ent > 0 else 0.0
                        elif row["Buy/Sell"] == "SELL":
                            pl_usd = round((precio_sal - precio_ent) * acciones_abs, 2)
                            pl_pct = round(((precio_sal - precio_ent) / precio_ent) * 100, 2)
                        else:
                            pl_usd = round((precio_ent - precio_sal) * acciones_abs, 2)
                            pl_pct = round(((precio_ent - precio_sal) / precio_ent) * 100, 2)

                        filas_finales.append([fecha_r, ticker_r, acciones_r, precio_ent, monto_r,
                                              precio_sal, pl_pct, pl_usd, "IBKR Import", usuario_actual, row["TradeIDs"]])

                # ============ SECCIÓN CASH TRANSACTIONS ============
                if filas_cash:
                    header_c = filas_cash[0]
                    df_cash = pd.DataFrame(filas_cash[1:], columns=header_c)
                    df_cash.columns = df_cash.columns.str.strip()

                    cols_cash_requeridas = {"Date/Time", "Type", "Amount"}
                    if not cols_cash_requeridas.issubset(set(df_cash.columns)):
                        st.error(f"⚠️ Columnas encontradas en Cash Transactions: {list(df_cash.columns)}")
                        st.stop()

                    tiene_transid = "TransactionID" in df_cash.columns
                    if tiene_transid:
                        filas_previas_cash = len(df_cash)
                        df_cash = df_cash[~df_cash["TransactionID"].astype(str).str.strip().isin(transids_existentes)]
                        cash_omitidos = filas_previas_cash - len(df_cash)
                    else:
                        df_cash["TransactionID"] = ""

                    df_cash["Amount"]    = pd.to_numeric(df_cash["Amount"], errors="coerce")
                    df_cash["FechaSolo"] = df_cash["Date/Time"].astype(str).str.split(";").str[0]
                    df_cash["Fecha_DT"]  = pd.to_datetime(df_cash["FechaSolo"], format="%Y%m%d", errors="coerce")
                    df_cash = df_cash.dropna(subset=["Amount", "Fecha_DT"])

                    for _, row in df_cash.iterrows():
                        tipo   = str(row.get("Type", "")).strip()
                        desc   = str(row.get("Description", "")).strip()
                        nota_r = f"{tipo}: {desc}" if desc else tipo
                        filas_cash_final.append([
                            usuario_actual,
                            row["Fecha_DT"].strftime("%Y-%m-%d"),
                            round(row["Amount"], 2),
                            nota_r,
                            str(row.get("TransactionID", "")).strip()
                        ])

                # ============ SECCIÓN OPEN POSITIONS ============
                # Es una FOTO del momento (no se acumula): se guarda tal cual viene,
                # reemplazando por completo el snapshot anterior de este usuario.
                valor_posiciones_total = 0.0
                if filas_posiciones:
                    header_p = filas_posiciones[0]
                    df_pos = pd.DataFrame(filas_posiciones[1:], columns=header_p)
                    df_pos.columns = df_pos.columns.str.strip()

                    cols_pos_requeridas = {"Symbol", "Side", "Quantity"}
                    if not cols_pos_requeridas.issubset(set(df_pos.columns)):
                        st.error(f"⚠️ Columnas encontradas en Open Positions: {list(df_pos.columns)}")
                        st.stop()

                    for col_num in ["Quantity", "CostBasisPrice", "MarkPrice", "PositionValue", "FifoPnlUnrealized"]:
                        if col_num in df_pos.columns:
                            df_pos[col_num] = pd.to_numeric(df_pos[col_num], errors="coerce").fillna(0.0)
                        else:
                            df_pos[col_num] = 0.0

                    valor_posiciones_total = df_pos["PositionValue"].sum()

                    for _, row in df_pos.iterrows():
                        signo   = 1 if str(row["Side"]).strip().upper() == "LONG" else -1
                        qty_r   = signo * abs(row["Quantity"])
                        filas_posiciones_final.append([
                            usuario_actual,
                            str(row["Symbol"]).strip(),
                            str(row["Side"]).strip(),
                            qty_r,
                            round(row["CostBasisPrice"], 4),
                            round(row["MarkPrice"], 4),
                            round(row["PositionValue"], 2),
                            round(row["FifoPnlUnrealized"], 2),
                            str(row.get("ReportDate", "")).strip()
                        ])

                # ============ SECCIÓN CASH REPORT ============
                # Capital Total Real = Efectivo (Ending Cash) + Valor de Posiciones Abiertas.
                # Esto REEMPLAZA el Capital Base — ya no se tipea a mano.
                if filas_cashreport:
                    header_cr = filas_cashreport[0]
                    df_cr = pd.DataFrame(filas_cashreport[1:], columns=header_cr)
                    df_cr.columns = df_cr.columns.str.strip()

                    cols_cr_requeridas = {"ToDate", "EndingCash"}
                    if not cols_cr_requeridas.issubset(set(df_cr.columns)):
                        st.error(f"⚠️ Columnas encontradas en Cash Report: {list(df_cr.columns)}")
                        st.stop()

                    df_cr["EndingCash"] = pd.to_numeric(df_cr["EndingCash"], errors="coerce").fillna(0.0)
                    df_cr["ToDate_DT"]  = pd.to_datetime(df_cr["ToDate"].astype(str), format="%Y%m%d", errors="coerce")
                    df_cr = df_cr.dropna(subset=["ToDate_DT"])

                    if not df_cr.empty:
                        fila_cr = df_cr.iloc[0]
                        ending_cash = fila_cr["EndingCash"]
                        capital_total_hoy = ending_cash + valor_posiciones_total
                        capital_calculado_ibkr = (round(capital_total_hoy, 2), fila_cr["ToDate_DT"].date())

                # --- ADVERTENCIAS ---
                if advertencias:
                    st.warning(
                        f"⚠️ Sin precio de entrada en este archivo para: **{', '.join(set(advertencias))}**. "
                        f"Su P/L quedará en $0. Edítalos manualmente después."
                    )
                if trades_omitidos > 0:
                    st.info(f"ℹ️ {trades_omitidos} ejecuciones de Trades ya habían sido importadas antes — se omitieron para no duplicar.")
                if cash_omitidos > 0:
                    st.info(f"ℹ️ {cash_omitidos} movimientos de Cash Transactions ya habían sido importados antes — se omitieron para no duplicar.")

                if not filas_finales and not filas_cash_final and not filas_posiciones_final and capital_calculado_ibkr is None:
                    st.warning("⚠️ No hay filas nuevas para importar (todo lo del archivo ya estaba cargado).")
                    st.stop()

                # --- PREVIEW TRADES ---
                if filas_finales:
                    st.success(f"✅ Trades: se procesaron **{len(filas_finales)} filas** listas para importar.")
                    st.markdown("#### Vista previa — Trades")
                    cols_preview = ["Fecha", "Ticker", "Acciones", "Precio Entrada",
                                    "Monto", "Precio Salida", "P/L %", "P/L $", "Notas", "Usuario", "TradeID"]
                    df_preview = pd.DataFrame(filas_finales, columns=cols_preview)
                    st.dataframe(df_preview, use_container_width=True, hide_index=True)

                # --- PREVIEW CASH TRANSACTIONS ---
                if filas_cash_final:
                    st.success(f"✅ Cash Transactions: se procesaron **{len(filas_cash_final)} movimientos** listos para importar.")
                    st.markdown("#### Vista previa — Movimientos de Capital")
                    cols_preview_cash = ["Usuario", "Fecha", "Monto", "Nota", "TransactionID"]
                    df_preview_cash = pd.DataFrame(filas_cash_final, columns=cols_preview_cash)
                    st.dataframe(df_preview_cash, use_container_width=True, hide_index=True)

                # --- PREVIEW OPEN POSITIONS ---
                if filas_posiciones_final:
                    st.success(f"✅ Open Positions: **{len(filas_posiciones_final)} posiciones** abiertas al {filas_posiciones_final[0][8] or 'hoy'}.")
                    st.markdown("#### Vista previa — Posiciones Abiertas (reemplaza el snapshot anterior)")
                    df_preview_pos = pd.DataFrame(filas_posiciones_final, columns=COLS_POSICIONES)
                    st.dataframe(df_preview_pos, use_container_width=True, hide_index=True)
                    st.caption("⚠️ Esto REEMPLAZA por completo tu Portafolio Activo — no se suma a lo anterior, se sustituye.")

                # --- PREVIEW CASH REPORT / CAPITAL REAL ---
                if capital_calculado_ibkr is not None:
                    capital_total_val, fecha_capital_val = capital_calculado_ibkr
                    st.success(f"✅ Cash Report: Capital Total Real al {fecha_capital_val.strftime('%d/%m/%Y')} = **${formato_es(capital_total_val)}**")
                    st.caption(
                        f"Efectivo (Ending Cash) + Valor de Posiciones Abiertas. "
                        f"Esto REEMPLAZA tu Capital Base — ya no hace falta escribirlo a mano."
                    )

                st.warning(
                    "⚠️ Revisa la vista previa antes de confirmar. "
                    "Esta acción escribe directamente en Google Sheets y no se puede deshacer automáticamente."
                )

                if st.button("💾 Confirmar e Importar a Sheets"):
                    try:
                        if filas_finales:
                            sheet.append_rows(filas_finales)
                        if filas_cash_final:
                            sheet_movimientos.append_rows(filas_cash_final)
                        if filas_posiciones_final:
                            # Reemplazar el snapshot: borrar filas viejas de este usuario, escribir las nuevas
                            filas_pos_todas = sheet_posiciones.get_all_values()
                            if len(filas_pos_todas) > 1:
                                header_pos_actual = filas_pos_todas[0]
                                idx_usuario_pos = header_pos_actual.index("Usuario") if "Usuario" in header_pos_actual else None
                                if idx_usuario_pos is not None:
                                    filas_otros_usuarios = [f for f in filas_pos_todas[1:] if len(f) > idx_usuario_pos and f[idx_usuario_pos] != usuario_actual]
                                else:
                                    filas_otros_usuarios = filas_pos_todas[1:]
                                sheet_posiciones.clear()
                                sheet_posiciones.append_row(header_pos_actual)
                                if filas_otros_usuarios:
                                    sheet_posiciones.append_rows(filas_otros_usuarios)
                            sheet_posiciones.append_rows(filas_posiciones_final)
                        if capital_calculado_ibkr is not None:
                            # Reemplazar Capital Base en config con el calculado desde IBKR
                            capital_total_val, fecha_capital_val = capital_calculado_ibkr
                            filas_config_actual = sheet_config.get_all_values()
                            fila_encontrada_cfg = None
                            for idx, fila in enumerate(filas_config_actual[1:], start=2):
                                if fila and fila[0] == usuario_actual:
                                    fila_encontrada_cfg = idx
                                    break
                            valores_cfg = [usuario_actual, capital_total_val, str(fecha_capital_val)]
                            if fila_encontrada_cfg:
                                sheet_config.update(f"A{fila_encontrada_cfg}:C{fila_encontrada_cfg}", [valores_cfg])
                            else:
                                sheet_config.append_row(valores_cfg)
                        st.success(
                            f"🎉 ¡Importación exitosa! Se guardaron **{len(filas_finales)} trades**, "
                            f"**{len(filas_cash_final)} movimientos de capital**, se actualizó el snapshot de "
                            f"**{len(filas_posiciones_final)} posiciones abiertas**"
                            + (f" y se actualizó tu Capital Base a **${formato_es(capital_calculado_ibkr[0])}**" if capital_calculado_ibkr else "")
                            + f". Haz clic en **Actualizar Bóveda** para verlos reflejados en las métricas."
                        )
                    except Exception as e:
                        st.error(f"Error al escribir en Google Sheets: {e}")

            except Exception as e:
                st.error(f"Error al procesar el archivo: {e}")
        else:
            st.info("👆 Sube un archivo CSV exportado desde el Flex Query de IBKR para comenzar.")

# ==========================================
# PESTAÑA 3: MÉTRICAS (Dashboard Avanzado)
# ==========================================
with tab_dash:
    st.subheader("📊 Métricas de Rendimiento y Análisis")
    st.markdown("##### ⚙️ Configuración y Filtros")

    f_col1, f_col2, f_col3 = st.columns(3)

    if conexion_exitosa and not df.empty:
        df_cerradas = df[df['P/L $'] != 0].copy()

        if not df_cerradas.empty:
            df_cerradas['Fecha_DT'] = pd.to_datetime(df_cerradas['Fecha'], errors='coerce', format='mixed')

            tickers_unicos = ["TODOS"] + sorted(df_cerradas['Ticker'].unique().tolist())
            with f_col2:
                ticker_filtro = st.selectbox("Filtrar por Ticker:", tickers_unicos)

            with f_col3:
                fechas_min   = df_cerradas['Fecha_DT'].min().date()
                fechas_max   = df_cerradas['Fecha_DT'].max().date()
                rango_fechas = st.date_input("Rango de Fechas:", [fechas_min, fechas_max], format="DD/MM/YYYY")

            # --- Proyección de capital hacia CUALQUIER fecha, adelante o atrás,
            # desde el Capital Base guardado (que ahora normalmente es "hoy",
            # calculado desde el Cash Report de IBKR, no una fecha fija del pasado).
            def capital_en_fecha(fecha_objetivo_dt):
                if capital_base_guardado is None or fecha_base_guardada is None:
                    return None
                fecha_base_dt = pd.to_datetime(fecha_base_guardada)
                if fecha_objetivo_dt == fecha_base_dt:
                    return capital_base_guardado
                elif fecha_objetivo_dt < fecha_base_dt:
                    # Retroceder en el tiempo: restar lo que pasó entre la fecha
                    # objetivo y la fecha base para "deshacerlo".
                    pl_medio = df_cerradas[
                        (df_cerradas['Fecha_DT'] >= fecha_objetivo_dt) &
                        (df_cerradas['Fecha_DT'] < fecha_base_dt)
                    ]['P/L $'].sum()
                    mov_medio = 0.0
                    if not df_movimientos.empty:
                        mov_medio = df_movimientos[
                            (df_movimientos['Fecha_DT'] >= fecha_objetivo_dt) &
                            (df_movimientos['Fecha_DT'] < fecha_base_dt)
                        ]['Monto'].sum()
                    return capital_base_guardado - pl_medio - mov_medio
                else:
                    # Avanzar en el tiempo: sumar lo que pasó entre la fecha base
                    # y la fecha objetivo.
                    pl_medio = df_cerradas[
                        (df_cerradas['Fecha_DT'] >= fecha_base_dt) &
                        (df_cerradas['Fecha_DT'] < fecha_objetivo_dt)
                    ]['P/L $'].sum()
                    mov_medio = 0.0
                    if not df_movimientos.empty:
                        mov_medio = df_movimientos[
                            (df_movimientos['Fecha_DT'] >= fecha_base_dt) &
                            (df_movimientos['Fecha_DT'] < fecha_objetivo_dt)
                        ]['Monto'].sum()
                    return capital_base_guardado + pl_medio + mov_medio

            # --- CAPITAL INICIAL: proyectado desde el Capital Base (IBKR o manual) ---
            with f_col1:
                if capital_base_guardado is not None and fecha_base_guardada is not None:
                    fecha_inicio_rango = rango_fechas[0] if len(rango_fechas) == 2 else fechas_min
                    capital_inicial = capital_en_fecha(pd.to_datetime(fecha_inicio_rango))

                    st.metric("Capital Inicial ($)", f"${formato_es(capital_inicial)}")
                    st.caption(
                        f"⚙️ Proyectado desde ${formato_es(capital_base_guardado)} "
                        f"({fecha_base_guardada.strftime('%d/%m/%Y')})."
                    )
                else:
                    capital_inicial = None

            st.write("---")

            # --- APLICAR FILTROS ---
            df_filtrado = df_cerradas.copy()
            if ticker_filtro != "TODOS":
                df_filtrado = df_filtrado[df_filtrado['Ticker'] == ticker_filtro]

            if len(rango_fechas) == 2:
                start_date, end_date = rango_fechas
                df_filtrado = df_filtrado[
                    (df_filtrado['Fecha_DT'].dt.date >= start_date) &
                    (df_filtrado['Fecha_DT'].dt.date <= end_date)
                ]

            # Movimientos de capital DENTRO del rango seleccionado (para Capital Final y curvas)
            movimientos_rango = pd.DataFrame(columns=['Fecha_DT', 'Monto'])
            if not df_movimientos.empty and len(rango_fechas) == 2:
                movimientos_rango = df_movimientos[
                    (df_movimientos['Fecha_DT'].dt.date >= start_date) &
                    (df_movimientos['Fecha_DT'].dt.date <= end_date)
                ][['Fecha_DT', 'Monto']]

            if capital_inicial is not None and not df_filtrado.empty:

                # --- CÁLCULOS POR OPERACIÓN COMPLETA ---
                df_operaciones = df_filtrado.groupby(
                    ['Ticker', 'Precio Entrada'], as_index=False
                ).agg(
                    PL_Total=('P/L $', 'sum'),
                    PL_Pct_Prom=('P/L %', 'mean'),
                    Fecha_DT=('Fecha_DT', 'min')
                )

                ganadoras  = df_operaciones[df_operaciones['PL_Total'] > 0]
                perdedoras = df_operaciones[df_operaciones['PL_Total'] < 0]

                total_trades   = len(df_operaciones)
                n_ganadoras    = len(ganadoras)
                n_perdedoras   = len(perdedoras)
                win_rate       = (n_ganadoras / total_trades) * 100 if total_trades > 0 else 0
                avg_win        = ganadoras['PL_Total'].mean()          if not ganadoras.empty  else 0
                avg_loss       = abs(perdedoras['PL_Total'].mean())    if not perdedoras.empty else 0
                avg_win_pct    = ganadoras['PL_Pct_Prom'].mean()       if not ganadoras.empty  else 0
                avg_loss_pct   = abs(perdedoras['PL_Pct_Prom'].mean()) if not perdedoras.empty else 0
                gross_profit   = ganadoras['PL_Total'].sum()
                gross_loss     = abs(perdedoras['PL_Total'].sum())
                profit_factor  = gross_profit / gross_loss if gross_loss > 0 else gross_profit
                pl_neto        = df_filtrado['P/L $'].sum()
                mov_neto_rango = movimientos_rango['Monto'].sum() if not movimientos_rango.empty else 0.0
                capital_final  = capital_inicial + pl_neto + mov_neto_rango
                rentabilidad_historica = (pl_neto / capital_inicial) * 100

                año_actual      = pd.Timestamp.now().year
                df_anual        = df_filtrado[df_filtrado['Fecha_DT'].dt.year == año_actual]
                pl_neto_anual   = df_anual['P/L $'].sum()

                # Capital al INICIO DEL AÑO ACTUAL (1-enero), no el inicio del rango
                # que esté viendo en pantalla — funciona hacia adelante o hacia atrás
                # según dónde caiga la fecha base respecto al 1-enero.
                fecha_inicio_anio_dt = pd.Timestamp(year=año_actual, month=1, day=1)
                capital_inicio_anio  = capital_en_fecha(fecha_inicio_anio_dt)
                if capital_inicio_anio is None:
                    capital_inicio_anio = capital_inicial

                rentabilidad_anual = (pl_neto_anual / capital_inicio_anio) * 100 if capital_inicio_anio else 0.0

                loss_rate = 100 - win_rate
                edge      = ((win_rate / 100) * avg_win) - ((loss_rate / 100) * avg_loss)

                df_diario_sharpe = df_filtrado.groupby('Fecha_DT')['P/L $'].sum()
                if len(df_diario_sharpe) > 1:
                    retorno_medio = df_diario_sharpe.mean()
                    desviacion    = df_diario_sharpe.std()
                    sharpe        = (retorno_medio / desviacion) * (252 ** 0.5) if desviacion > 0 else 0
                else:
                    sharpe = 0

                # Serie diaria combinada: P/L de trades + movimientos de capital (para Balance/Drawdown/Equidad)
                df_diario_trades_dd = df_filtrado.groupby('Fecha_DT', as_index=False)['P/L $'].sum()
                if not movimientos_rango.empty:
                    df_diario_mov_dd = movimientos_rango.groupby('Fecha_DT', as_index=False)['Monto'].sum()
                    df_diario_mov_dd = df_diario_mov_dd.rename(columns={'Monto': 'P/L $'})
                    df_diario_dd = pd.concat([df_diario_trades_dd, df_diario_mov_dd])
                    df_diario_dd = df_diario_dd.groupby('Fecha_DT', as_index=False)['P/L $'].sum()
                else:
                    df_diario_dd = df_diario_trades_dd
                df_diario_dd = df_diario_dd.sort_values('Fecha_DT')
                df_diario_dd['Balance']    = capital_inicial + df_diario_dd['P/L $'].cumsum()
                df_diario_dd['Peak']       = df_diario_dd['Balance'].cummax()
                df_diario_dd['Drawdown_$'] = df_diario_dd['Balance'] - df_diario_dd['Peak']
                df_diario_dd['Drawdown_%'] = (df_diario_dd['Drawdown_$'] / df_diario_dd['Peak']) * 100
                max_drawdown_pct = df_diario_dd['Drawdown_%'].min()
                max_drawdown_usd = df_diario_dd['Drawdown_$'].min()

                pl_lista = df_operaciones.sort_values('Fecha_DT')['PL_Total'].tolist()
                racha    = 0
                if pl_lista:
                    ultimo = 1 if pl_lista[-1] > 0 else -1
                    for pl in reversed(pl_lista):
                        if (pl > 0 and ultimo == 1) or (pl < 0 and ultimo == -1):
                            racha += 1
                        else:
                            break
                racha_texto = f"🟢 {racha} ganadoras" if ultimo == 1 else f"🔴 {racha} perdedoras"

                # --- FORMATEO ---
                win_rate_str      = f"{win_rate:.1f}".replace(".", ",")
                pf_str            = formato_es(profit_factor)
                rent_hist_str     = f"{rentabilidad_historica:.2f}".replace(".", ",")
                rent_anual_str    = f"{rentabilidad_anual:.2f}".replace(".", ",")
                sharpe_str        = f"{sharpe:.2f}".replace(".", ",")
                dd_pct_str        = f"{max_drawdown_pct:.2f}".replace(".", ",")
                dd_usd_str        = formato_es(abs(max_drawdown_usd))
                avg_win_pct_str   = f"{avg_win_pct:.2f}".replace(".", ",")
                avg_loss_pct_str  = f"{avg_loss_pct:.2f}".replace(".", ",")

                # --- FILA 0: CONTADOR ---
                st.markdown("#### Operaciones")
                o1, o2, o3 = st.columns(3)
                o1.metric("Total Operaciones", total_trades)
                o2.metric("Ganadoras 🟢",      n_ganadoras)
                o3.metric("Perdedoras 🔴",      n_perdedoras)

                st.write("")

                # --- FILA 1: CAPITAL ---
                st.markdown("#### Métricas Clave")
                r1, r2, r3, r4 = st.columns(4)
                r1.metric("Capital Final",                       f"${formato_es(capital_final)}")
                r2.metric("P/L Neto",                           f"${formato_es(pl_neto)}")
                r3.metric("Rentabilidad Histórica",             f"{rent_hist_str}%")
                r4.metric(f"Rentabilidad Anual ({año_actual})", f"{rent_anual_str}%")

                st.write("")

                # --- FILA 2: KPIs ---
                k1, k2, k3, k4 = st.columns(4)
                k1.metric("Win Rate",      f"{win_rate_str}%")
                k2.metric("Profit Factor", pf_str)
                k3.metric("Avg Win",       f"${formato_es(avg_win)}",  delta=f"{avg_win_pct_str}%",   delta_color="off")
                k4.metric("Avg Loss",      f"${formato_es(avg_loss)}", delta=f"-{avg_loss_pct_str}%", delta_color="off")

                st.write("")

                # --- FILA 3: AVANZADAS ---
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Expectativa (Edge)", f"${formato_es(edge)}")
                m2.metric("Sharpe Ratio",       sharpe_str)
                m3.metric("Max Drawdown",       f"{dd_pct_str}%", delta=f"-${dd_usd_str}", delta_color="off")
                m4.metric("Racha Actual",       racha_texto)

                # Alerta drawdown actual
                drawdown_actual_pct = df_diario_dd['Drawdown_%'].iloc[-1]
                drawdown_actual_usd = df_diario_dd['Drawdown_$'].iloc[-1]
                dd_actual_pct_str   = f"{drawdown_actual_pct:.2f}".replace(".", ",")
                dd_actual_usd_str   = formato_es(abs(drawdown_actual_usd))

                if drawdown_actual_pct <= -10:
                    st.error(
                        f"🚨 **ALERTA DE DRAWDOWN:** Tu drawdown actual es de **{dd_actual_pct_str}%** "
                        f"(${dd_actual_usd_str}). Según tu sistema, debes **cerrar todas las posiciones** "
                        f"y mantenerte fuera del mercado hasta que las condiciones mejoren."
                    )

                st.write("---")

                # --- CURVA DE EQUIDAD ---
                st.markdown("#### 📈 Curva de Equidad")
                df_diario = df_diario_dd[['Fecha_DT', 'P/L $', 'Balance']].copy()
                df_diario = df_diario.rename(columns={'Balance': 'Balance de Cuenta'})

                chart_equidad = alt.Chart(df_diario).mark_line(
                    color='#2962ff',
                    strokeWidth=2.5,
                    point=alt.OverlayMarkDef(color='#2962ff', size=60, filled=True)
                ).encode(
                    x=alt.X('Fecha_DT:T', title='',
                            axis=alt.Axis(format='%d-%m-%Y', labelAngle=-45, tickCount='month', grid=True)),
                    y=alt.Y('Balance de Cuenta:Q', title='Equidad ($)', scale=alt.Scale(zero=False)),
                    tooltip=[
                        alt.Tooltip('Fecha_DT:T',          title='Fecha',                    format='%d-%m-%Y'),
                        alt.Tooltip('P/L $:Q',             title='P/L + Movimientos del Día', format='$,.2f'),
                        alt.Tooltip('Balance de Cuenta:Q', title='Capital',                   format='$,.2f')
                    ]
                ).properties(height=350).interactive()
                st.altair_chart(chart_equidad, use_container_width=True)

                st.write("---")

                # --- HISTORIAL ---
                st.markdown("#### 📋 Historial de Operaciones Cerradas")
                columnas_mostrar = ['Fecha', 'Ticker', 'Acciones', 'Precio Entrada', 'Precio Salida', 'P/L %', 'P/L $', 'Notas']
                df_mostrar = df_filtrado[columnas_mostrar].copy()
                df_mostrar['Fecha']          = pd.to_datetime(df_mostrar['Fecha']).dt.strftime('%d/%m/%Y')
                df_mostrar['Precio Entrada'] = df_mostrar['Precio Entrada'].apply(lambda x: f"${formato_es(x)}")
                df_mostrar['Precio Salida']  = df_mostrar['Precio Salida'].apply(lambda x: f"${formato_es(x)}")
                df_mostrar['P/L %']          = df_mostrar['P/L %'].apply(lambda x: f"{formato_es(x)}%")
                df_mostrar['P/L $']          = df_mostrar['P/L $'].apply(lambda x: f"${formato_es(x)}")
                st.dataframe(df_mostrar, use_container_width=True, hide_index=True)

            elif capital_inicial is None:
                st.warning(
                    "⚠️ Configura tu **Capital Base** en Bitácora → Registro Histórico "
                    "para ver las Métricas de Rendimiento."
                )
            else:
                st.warning("⚠️ No hay operaciones que coincidan con los filtros seleccionados.")
        else:
            st.info("💡 Aún no hay operaciones cerradas registradas para calcular métricas.")
    else:
        st.warning("⚠️ No hay datos en la base de datos o revisa tu conexión.")

    st.write("---")
    st.markdown("### ⚙️ Administración de Datos")
    with st.expander("🗑️ Eliminar un registro de la base de datos"):
        st.warning("⚠️ Cuidado: Al eliminar un registro, se borrará definitivamente de la base de datos.")
        df_eliminar = pd.DataFrame(sheet.get_all_records())
        if not df_eliminar.empty:
            if 'Usuario' in df_eliminar.columns:
                df_eliminar = df_eliminar[df_eliminar['Usuario'] == usuario_actual]
            if not df_eliminar.empty:
                df_eliminar['Fila_Excel'] = df_eliminar.index + 2
                col_1 = df_eliminar.columns[0]
                col_2 = df_eliminar.columns[1]
                col_3 = df_eliminar.columns[2]
                df_eliminar['Etiqueta'] = (
                    df_eliminar[col_1].astype(str) + " | " +
                    df_eliminar[col_2].astype(str) + " | Acciones: " +
                    df_eliminar[col_3].astype(str)
                )
                opciones_borrar = dict(zip(df_eliminar['Etiqueta'], df_eliminar['Fila_Excel']))
                trade_a_borrar  = st.selectbox(
                    "Selecciona la operación que deseas eliminar:",
                    options=[""] + list(opciones_borrar.keys())
                )
                if st.button("🗑️ Eliminar Definitivamente"):
                    if trade_a_borrar != "":
                        fila_exacta = opciones_borrar[trade_a_borrar]
                        sheet.delete_rows(int(fila_exacta))
                        st.success("✅ Registro eliminado con éxito.")
                        st.rerun()
                    else:
                        st.error("⚠️ Por favor, selecciona una operación de la lista.")
            else:
                st.info("No tienes operaciones registradas para eliminar.")
        else:
            st.info("No hay operaciones registradas en la base de datos.")

    with st.expander("🔥 Borrar TODO mi Registro (Trades + Movimientos + Capital Base)"):
        st.error(
            "⚠️ **Esto borra permanentemente TODOS tus datos históricos:** "
            "todos tus trades en la Bitácora, todos tus movimientos de capital "
            "(depósitos/retiros/comisiones importados) y tu Capital Base configurado. "
            "Los datos de otros usuarios que compartan este Google Sheet NO se tocan. "
            "**No se puede deshacer.**"
        )
        confirmar_check = st.checkbox(
            "Entiendo que esta acción es irreversible y borra TODO mi historial.",
            key="check_borrar_todo"
        )
        confirmar_texto = st.text_input(
            'Escribe exactamente "BORRAR TODO" para habilitar el botón:',
            key="texto_borrar_todo"
        )
        if st.button("🔥 Borrar TODO Mi Registro Definitivamente"):
            if not confirmar_check:
                st.error("⚠️ Marca la casilla de confirmación primero.")
            elif confirmar_texto.strip() != "BORRAR TODO":
                st.error('⚠️ El texto debe ser exactamente "BORRAR TODO" (sin comillas).')
            else:
                try:
                    # --- Journal: conservar solo filas de OTROS usuarios ---
                    filas_journal = sheet.get_all_values()
                    if len(filas_journal) > 1:
                        header_j = filas_journal[0]
                        idx_usuario_j = header_j.index("Usuario") if "Usuario" in header_j else None
                        if idx_usuario_j is not None:
                            filas_mantener_j = [f for f in filas_journal[1:] if len(f) > idx_usuario_j and f[idx_usuario_j] != usuario_actual]
                        else:
                            filas_mantener_j = filas_journal[1:]
                        sheet.clear()
                        sheet.append_row(header_j)
                        if filas_mantener_j:
                            sheet.append_rows(filas_mantener_j)

                    # --- Movimientos: conservar solo filas de OTROS usuarios ---
                    filas_mov_todas = sheet_movimientos.get_all_values()
                    if len(filas_mov_todas) > 1:
                        header_m = filas_mov_todas[0]
                        idx_usuario_m = header_m.index("Usuario") if "Usuario" in header_m else None
                        if idx_usuario_m is not None:
                            filas_mantener_m = [f for f in filas_mov_todas[1:] if len(f) > idx_usuario_m and f[idx_usuario_m] != usuario_actual]
                        else:
                            filas_mantener_m = filas_mov_todas[1:]
                        sheet_movimientos.clear()
                        sheet_movimientos.append_row(header_m)
                        if filas_mantener_m:
                            sheet_movimientos.append_rows(filas_mantener_m)

                    # --- Config (Capital Base): conservar solo filas de OTROS usuarios ---
                    filas_config_todas = sheet_config.get_all_values()
                    if len(filas_config_todas) > 1:
                        header_c = filas_config_todas[0]
                        idx_usuario_c = header_c.index("Usuario") if "Usuario" in header_c else None
                        if idx_usuario_c is not None:
                            filas_mantener_c = [f for f in filas_config_todas[1:] if len(f) > idx_usuario_c and f[idx_usuario_c] != usuario_actual]
                        else:
                            filas_mantener_c = filas_config_todas[1:]
                        sheet_config.clear()
                        sheet_config.append_row(header_c)
                        if filas_mantener_c:
                            sheet_config.append_rows(filas_mantener_c)

                    st.success("✅ Tu historial completo fue borrado. Ve a Registro Histórico para configurar tu nuevo Capital Base y empezar a importar desde IBKR.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al borrar el historial: {e}")