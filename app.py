import streamlit as st
import pandas as pd
from datetime import datetime
import hashlib
import urllib.parse
from fpdf import FPDF
from supabase import create_client, Client
import cloudinary
import cloudinary.uploader

# ==========================================
# 1. CONFIGURAÇÕES E CONEXÕES
# ==========================================
st.set_page_config(page_title="Usina Municipal de Vilhena", layout="wide", page_icon="🏭")

try:
    url: str = st.secrets["SUPABASE_URL"]
    key: str = st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(url, key)
except:
    st.error("Erro de conexão com Supabase.")
    st.stop()

# Cloudinary (opcional)
try:
    cloudinary.config(cloud_name=st.secrets["CLOUDINARY_NAME"], api_key=st.secrets["CLOUDINARY_KEY"], api_secret=st.secrets["CLOUDINARY_SECRET"], secure=True)
except: pass

# ==========================================
# 2. FUNÇÕES DE APOIO
# ==========================================
def gerar_hash_senha(senha): return hashlib.sha256(str.encode(senha)).hexdigest()
def verificar_senha(senha, hash_armazenado): return gerar_hash_senha(senha) == hash_armazenado

def gerar_pdf_ticket(dados):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(190, 10, "PREFEITURA MUNICIPAL DE VILHENA", ln=True, align="C")
    pdf.ln(10)
    pdf.set_font("Arial", "", 11)
    for k, v in dados.items():
        if k != "foto_url":
            pdf.cell(50, 8, f"{str(k).upper()}:", border=1)
            pdf.cell(140, 8, f"{str(v)}", border=1, ln=True)
    res = pdf.output(dest="S")
    return bytes(res) if isinstance(res, (bytes, bytearray)) else res.encode("latin-1", "replace")

def dar_baixa_estoque_cbuq(peso_liquido_kg):
    res_traco = supabase.table("config_traco").select("*").execute()
    if res_traco.data:
        for row in res_traco.data:
            qtd = peso_liquido_kg * (row['porcentagem'] / 100)
            res_at = supabase.table("estoque_insumos").select("quantidade_kg").eq("item", row['item']).execute()
            if res_at.data:
                nova = res_at.data[0]['quantidade_kg'] - qtd
                supabase.table("estoque_insumos").update({"quantidade_kg": nova}).eq("item", row['item']).execute()

def atualizar_estoque_direto(material, peso, op="soma"):
    res = supabase.table("estoque_insumos").select("quantidade_kg").eq("item", material).execute()
    if res.data:
        nova = (res.data[0]['quantidade_kg'] + peso) if op == "soma" else (res.data[0]['quantidade_kg'] - peso)
        supabase.table("estoque_insumos").update({"quantidade_kg": nova}).eq("item", material).execute()

# ==========================================
# 3. ACESSO
# ==========================================
if "autenticado" not in st.session_state: st.session_state.update({"autenticado": False, "usuario": "", "perfil": ""})

if not st.session_state["autenticado"]:
    st.title("🏛️ Sistema Usina Municipal")
    with st.form("login"):
        u, p = st.text_input("Usuário"), st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            res = supabase.table("usuarios").select("*").eq("usuario", u.lower()).execute()
            if res.data and verificar_senha(p, res.data[0]['senha_hash']):
                st.session_state.update({"autenticado": True, "usuario": u, "perfil": res.data[0]['perfil']})
                st.rerun()
            else: st.error("Erro no login.")
    st.stop()

# ==========================================
# 4. DASHBOARD & ABAS
# ==========================================
st.sidebar.button("Sair", on_click=lambda: st.session_state.update({"autenticado": False}))
tabs = st.tabs(["📊 Dashboard", "🚛 Balança", "🏗️ Traço", "📦 Almoxarifado", "🛠️ Manutenção", "👤 Admin"])

# --- TAB 1: DASHBOARD ---
with tabs[0]:
    st.header("Insumos de Produção")
    res = supabase.table("estoque_insumos").select("*").execute()
    if res.data:
        df = pd.DataFrame(res.data)
        m = st.columns(len(df))
        for i, r in df.iterrows(): m[i].metric(r['item'], f"{r['quantidade_kg']:,.0f} kg")

# --- TAB 2: BALANÇA ---
with tabs[1]:
    st.subheader("Entrada e Saída de Materiais")
    c1, c2 = st.columns(2)
    with c1:
        placa = st.text_input("Placa").upper()
        tipo = st.selectbox("Operação", ["Saída (Massa Asfáltica)", "Entrada (Insumo)", "Saída (Diversos)"])
        if tipo == "Saída (Massa Asfáltica)": material, destino = "Massa Asfáltica CBUQ", st.text_input("Destino")
        elif tipo == "Entrada (Insumo)": material, destino = st.selectbox("Insumo", ["CAP", "Pó de Brita", "Brita 0", "Brita 3/4", "Imprimante", "Cola"]), "Usina"
        else: material, destino = st.text_input("Material Diversos"), st.text_input("Destino")
        p_l = st.number_input("Peso Líquido (kg)", 0.0)
    with c2:
        foto = st.camera_input("Foto")
        if st.button("💾 Salvar Pesagem"):
            dados = {"placa": placa, "tipo_movimento": tipo, "material": material, "peso_liquido": p_l, "destino": destino, "operador": st.session_state['usuario']}
            supabase.table("balanca").insert(dados).execute()
            if tipo == "Entrada (Insumo)": atualizar_estoque_direto(material, p_l, "soma")
            elif tipo == "Saída (Massa Asfáltica)": dar_baixa_estoque_cbuq(p_l)
            elif tipo == "Saída (Diversos)": atualizar_estoque_direto(material, p_l, "subtrai")
            st.success("Salvo!"); st.download_button("📥 PDF", gerar_pdf_ticket(dados), f"ticket_{placa}.pdf")

# --- TAB 3: TRAÇO ---
with tabs[2]:
    st.subheader("Configuração do Traço")
    res_t = supabase.table("config_traco").select("*").execute()
    if res_t.data:
        with st.form("f_traco"):
            n_perc = {}
            for r in res_t.data: n_perc[r['item']] = st.number_input(f"% {r['item']}", 0.0, 100.0, float(r['porcentagem']))
            if st.form_submit_button("Salvar Traço"):
                for k, v in n_perc.items(): supabase.table("config_traco").update({"porcentagem": v}).eq("item", k).execute()
                st.rerun()

# --- TAB 4: ALMOXARIFADO (NOVA) ---
with tabs[3]:
    st.header("📦 Controle de Almoxarifado")
    menu = st.radio("Ação:", ["Ver Estoque", "Lançar Entrada/Saída", "Cadastrar Novo Item"], horizontal=True)
    
    if menu == "Ver Estoque":
        res_alm = supabase.table("almoxarifado").select("*").execute()
        if res_alm.data:
            df_alm = pd.DataFrame(res_alm.data)
            st.dataframe(df_alm[['item', 'categoria', 'quantidade', 'unidade']], use_container_width=True)
    
    elif menu == "Lançar Entrada/Saída":
        res_itens = supabase.table("almoxarifado").select("item").execute()
        itens_lista = [r['item'] for r in res_itens.data]
        if itens_lista:
            with st.form("f_mov_alm"):
                item_sel = st.selectbox("Selecione o Item", itens_lista)
                mov_tipo = st.selectbox("Tipo", ["Entrada (+)", "Saída (-)"])
                qtd_mov = st.number_input("Quantidade", min_value=0.1)
                if st.form_submit_button("Confirmar Movimentação"):
                    res_q = supabase.table("almoxarifado").select("quantidade").eq("item", item_sel).execute()
                    nova_q = (res_q.data[0]['quantidade'] + qtd_mov) if "Entrada" in mov_tipo else (res_q.data[0]['quantidade'] - qtd_mov)
                    supabase.table("almoxarifado").update({"quantidade": nova_q}).eq("item", item_sel).execute()
                    st.success(f"Estoque de {item_sel} atualizado!"); st.rerun()
    
    elif menu == "Cadastrar Novo Item":
        with st.form("f_novo_item"):
            n_item = st.text_input("Nome do Material")
            n_cat = st.selectbox("Categoria", ["Escritório", "Manutenção", "Consumo/Limpeza", "EPis", "Outros"])
            n_un = st.selectbox("Unidade de Medida", ["Unidade", "Litro", "Caixa", "Pacote", "Kg", "Metro"])
            if st.form_submit_button("Cadastrar Item"):
                try:
                    supabase.table("almoxarifado").insert({"item": n_item, "categoria": n_cat, "unidade": n_un, "quantidade": 0}).execute()
                    st.success("Item cadastrado!"); st.rerun()
                except: st.error("Item já existe ou erro na conexão.")

# --- TAB 5: MANUTENÇÃO ---
with tabs[4]:
    st.subheader("Diário de Paradas")
    with st.form("f_manut"):
        mot = st.selectbox("Motivo", ["Preventiva", "Quebra", "Chuva", "Insumo"])
        d1, h1 = st.date_input("Início"), st.time_input("Hora Início")
        d2, h2 = st.date_input("Fim"), st.time_input("Hora Fim")
        if st.form_submit_button("Registrar Parada"):
            t = (datetime.combine(d2, h2) - datetime.combine(d1, h1)).total_seconds() / 3600
            supabase.table("manutencao_paradas").insert({"motivo": mot, "tempo": round(t, 2)}).execute()
            st.success(f"Registrado {t:.2f}h")

# --- TAB 6: ADMIN ---
with tabs[5]:
    if st.session_state["perfil"] == "Administrador":
        if st.button("Resetar Insumos"):
            for i in ["CAP", "Pó de Brita", "Brita 0", "Brita 3/4", "Imprimante", "Cola"]:
                try: supabase.table("estoque_insumos").insert({"item": i, "quantidade_kg": 0}).execute()
                except: pass