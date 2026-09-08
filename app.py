import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta
import hashlib
import urllib.parse
from fpdf import FPDF
from supabase import create_client, Client
import cloudinary
import cloudinary.uploader

# ==========================================
# 1. CONFIGURAÇÕES E ESTILIZAÇÃO CSS
# ==========================================
st.set_page_config(page_title="Usina Municipal de Vilhena", layout="wide", page_icon="🏭")

st.markdown("""
    <style>
    [data-testid="stCameraInputButton"] { visibility: hidden; position: relative; }
    [data-testid="stCameraInputButton"]:after {
        content: '📸 Tirar Foto'; visibility: visible; position: absolute;
        left: 50%; top: 50%; transform: translate(-50%, -50%);
        background-color: #007bff; color: white; padding: 10px 20px; border-radius: 5px;
    }
    [data-testid="stCameraInputClearButton"] { visibility: hidden; position: relative; }
    [data-testid="stCameraInputClearButton"]:after {
        content: '➕ Próxima Foto / Limpar'; visibility: visible; position: absolute;
        left: 50%; top: 50%; transform: translate(-50%, -50%);
        background-color: #6c757d; color: white; padding: 10px 20px; border-radius: 5px;
    }
    .stMetric { background-color: white; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); border: 1px solid #eee; }
    </style>
""", unsafe_allow_html=True)

# Conexão Supabase
try:
    supabase: Client = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
except:
    st.error("Erro de conexão com banco de dados.")
    st.stop()

# Conexão Cloudinary
try:
    cloudinary.config(cloud_name=st.secrets["CLOUDINARY_NAME"], api_key=st.secrets["CLOUDINARY_KEY"], api_secret=st.secrets["CLOUDINARY_SECRET"], secure=True)
except: pass

# ==========================================
# 2. FUNÇÕES DE APOIO
# ==========================================
def formatar_peso(valor):
    """Transforma 10000 em 10.000 (padrão brasileiro para milhar)"""
    return f"{valor:,.0f}".replace(",", ".")

def gerar_hash_senha(senha): 
    return hashlib.sha256(str.encode(senha)).hexdigest()

def verificar_estoque_insuficiente(peso_liquido_kg):
    res_traco = supabase.table("config_traco").select("*").execute()
    alertas = []
    if res_traco.data:
        for row in res_traco.data:
            qtd_necessaria = peso_liquido_kg * (row['porcentagem'] / 100)
            res_at = supabase.table("estoque_insumos").select("quantidade_kg").eq("item", row['item']).execute()
            if res_at.data and res_at.data[0]['quantidade_kg'] < qtd_necessaria:
                alertas.append(f"{row['item']} (Faltam {formatar_peso(qtd_necessaria - res_at.data[0]['quantidade_kg'])} kg)")
    return alertas

def dar_baixa_estoque_cbuq(peso_liquido_kg):
    res_traco = supabase.table("config_traco").select("*").execute()
    if res_traco.data:
        for row in res_traco.data:
            qtd = peso_liquido_kg * (row['porcentagem'] / 100)
            res_at = supabase.table("estoque_insumos").select("quantidade_kg").eq("item", row['item']).execute()
            if res_at.data:
                nova = max(0, res_at.data[0]['quantidade_kg'] - qtd)
                supabase.table("estoque_insumos").update({"quantidade_kg": nova}).eq("item", row['item']).execute()

def atualizar_estoque_direto(material, peso, op="soma"):
    res = supabase.table("estoque_insumos").select("quantidade_kg").eq("item", material).execute()
    if res.data:
        nova = max(0, (res.data[0]['quantidade_kg'] + peso) if op == "soma" else (res.data[0]['quantidade_kg'] - peso))
        supabase.table("estoque_insumos").update({"quantidade_kg": nova}).eq("item", material).execute()

def gerar_pdf_ticket(dados):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(190, 10, "PREFEITURA MUNICIPAL DE VILHENA - SEMOSP", ln=True, align="C")
    pdf.ln(10)
    pdf.set_font("Arial", "", 12)
    for k, v in dados.items():
        if k not in ["foto_url"]:
            val = formatar_peso(v) if k == "peso_liquido" else str(v)
            pdf.set_fill_color(240, 240, 240)
            pdf.cell(60, 10, f" {str(k).upper().replace('_', ' ')}", border=1, fill=True)
            pdf.cell(130, 10, f" {val}", border=1, ln=True)
    return pdf.output(dest="S").encode("latin-1", "replace")

# ==========================================
# 3. CONTROLE DE ACESSO
# ==========================================
if "autenticado" not in st.session_state: 
    st.session_state.update({"autenticado": False, "usuario": "", "perfil": "", "fotos_temp": []})

if not st.session_state["autenticado"]:
    st.title("🏛️ Usina Municipal de Vilhena")
    c1, _ = st.columns([1, 2])
    with c1.form("login"):
        u = st.text_input("Usuário").lower().strip()
        p = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar", use_container_width=True):
            res = supabase.table("usuarios").select("*").eq("usuario", u).execute()
            if res.data and gerar_hash_senha(p) == res.data[0]['senha_hash']:
                st.session_state.update({"autenticado": True, "usuario": u, "nome": res.data[0]['nome'], "perfil": res.data[0]['perfil']})
                st.rerun()
            else: st.error("Acesso negado.")
    st.stop()

# ==========================================
# 4. INTERFACE
# ==========================================
st.sidebar.title(f"👤 {st.session_state['nome']}")
if st.sidebar.button("Sair"):
    st.session_state.update({"autenticado": False, "fotos_temp": []}); st.rerun()

abas = {
    "Administrador": ["📊 Dashboard", "🚛 Balança", "🏗️ Traço CBUQ", "📦 Almoxarifado", "🛠️ Manutenção", "📈 Relatórios", "👥 Usuários"],
    "Operador Balança": ["📊 Dashboard", "🚛 Balança", "📈 Relatórios"],
    "Gestor Almoxarifado/Manutenção": ["📊 Dashboard", "📦 Almoxarifado", "🛠️ Manutenção", "📈 Relatórios"]
}
tabs = st.tabs(abas.get(st.session_state["perfil"]))
tab_map = {aba: tabs[i] for i, aba in enumerate(abas.get(st.session_state["perfil"]))}

# --- DASHBOARD ---
if "📊 Dashboard" in tab_map:
    with tab_map["📊 Dashboard"]:
        st.header("Estoque Atual de Insumos")
        res = supabase.table("estoque_insumos").select("*").execute()
        if res.data:
            df = pd.DataFrame(res.data)
            cols = st.columns(len(df))
            for i, r in df.iterrows():
                # Formatação com ponto no Dashboard
                cols[i].metric(r['item'], f"{formatar_peso(r['quantidade_kg'])} kg")
            st.bar_chart(df.set_index("item")["quantidade_kg"])

# --- BALANÇA ---
if "🚛 Balança" in tab_map:
    with tab_map["🚛 Balança"]:
        c1, c2 = st.columns(2)
        with c1:
            placa = st.text_input("Placa").upper()
            motorista = st.text_input("Motorista")
            tipo = st.selectbox("Operação", ["Saída (Massa Asfáltica)", "Entrada (Insumo)", "Saída (Diversos)"])
            material = "Massa Asfáltica CBUQ" if tipo == "Saída (Massa Asfáltica)" else st.text_input("Material")
            destino = st.text_input("Destino")
            peso = st.number_input("Peso Líquido (kg)", min_value=0.0, step=10.0)
        with c2:
            foto = st.camera_input("Capturar Foto")
            if foto and foto.id not in [f.id for f in st.session_state["fotos_temp"]]:
                st.session_state["fotos_temp"].append(foto)
            if st.session_state["fotos_temp"]:
                st.write(f"📸 Fotos capturadas: {len(st.session_state['fotos_temp'])}")
                if st.button("Limpar Fotos"): st.session_state["fotos_temp"] = []; st.rerun()

        if st.button("💾 SALVAR REGISTRO", use_container_width=True, type="primary"):
            if placa and motorista and peso > 0:
                if tipo == "Saída (Massa Asfáltica)":
                    faltantes = verificar_estoque_insuficiente(peso)
                    if faltantes: st.error(f"Estoque insuficiente: {', '.join(faltantes)}"); st.stop()
                
                with st.spinner("Salvando..."):
                    urls = [cloudinary.uploader.upload(f)["secure_url"] for f in st.session_state["fotos_temp"]]
                    dados = {"placa": placa, "motorista": motorista, "tipo_movimento": tipo, "material": material, "peso_liquido": peso, "destino": destino, "operador": st.session_state['usuario'], "foto_url": ",".join(urls)}
                    supabase.table("balanca").insert(dados).execute()
                    if tipo == "Entrada (Insumo)": atualizar_estoque_direto(material, peso, "soma")
                    elif tipo == "Saída (Massa Asfáltica)": dar_baixa_estoque_cbuq(peso)
                    st.success("Salvo!"); st.session_state["fotos_temp"] = []
                    st.download_button("📥 PDF Ticket", gerar_pdf_ticket(dados), f"{placa}.pdf")

# --- RELATÓRIOS ---
if "📈 Relatórios" in tab_map:
    with tab_map["📈 Relatórios"]:
        t1, t2 = st.tabs(["Resumo Hoje", "Consulta"])
        with t1:
            res_h = supabase.table("balanca").select("*").gte("created_at", date.today().isoformat()).execute()
            if res_h.data:
                df_h = pd.DataFrame(res_h.data)
                txt = f"*🏛️ USINA VILHENA - {date.today().strftime('%d/%m/%Y')}*\n\n"
                for mat, qtd in df_h.groupby('material')['peso_liquido'].sum().items():
                    # Formatação com ponto no WhatsApp
                    txt += f"• {mat}: {formatar_peso(qtd)} kg\n"
                st.markdown(f"[🟢 Enviar WhatsApp](https://wa.me/?text={urllib.parse.quote(txt)})")
                st.dataframe(df_h, use_container_width=True)
        with t2:
            d_ini = st.date_input("De", date.today() - timedelta(days=7))
            d_fim = st.date_input("Até", date.today())
            res_hist = supabase.table("balanca").select("*").gte("created_at", d_ini.isoformat()).lte("created_at", d_fim.isoformat() + "T23:59:59").execute()
            if res_hist.data:
                for r in res_hist.data:
                    # Formatação com ponto no Histórico
                    with st.expander(f"{r['placa']} - {r['material']} - {formatar_peso(r['peso_liquido'])} kg"):
                        st.write(f"Motorista: {r['motorista']} | Destino: {r['destino']}")
                        if r['foto_url']:
                            for link in r['foto_url'].split(","): st.image(link, width=200)

# (Traço, Almoxarifado e Manutenção seguem a mesma lógica de inserção do banco anterior)