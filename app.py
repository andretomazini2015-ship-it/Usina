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
    st.error("Erro de conexão com Supabase. Verifique os Secrets.")
    st.stop()

try:
    cloudinary.config(
        cloud_name=st.secrets["CLOUDINARY_NAME"], 
        api_key=st.secrets["CLOUDINARY_KEY"], 
        api_secret=st.secrets["CLOUDINARY_SECRET"], 
        secure=True
    )
except: pass

# ==========================================
# 2. FUNÇÕES DE APOIO
# ==========================================
def gerar_hash_senha(senha): 
    return hashlib.sha256(str.encode(senha)).hexdigest()

def verificar_senha(senha, hash_armazenado): 
    return gerar_hash_senha(senha) == hash_armazenado

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
# 3. CONTROLE DE ACESSO
# ==========================================
if "autenticado" not in st.session_state: 
    st.session_state.update({"autenticado": False, "usuario": "", "perfil": ""})

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
        st.bar_chart(df.set_index("item")["quantidade_kg"])

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
            if placa and p_l > 0:
                url_foto = ""
                if foto:
                    try: url_foto = cloudinary.uploader.upload(foto)["secure_url"]
                    except: pass
                dados = {"placa": placa, "tipo_movimento": tipo, "material": material, "peso_liquido": p_l, "destino": destino, "operador": st.session_state['usuario'], "foto_url": url_foto}
                try:
                    supabase.table("balanca").insert(dados).execute()
                    if tipo == "Entrada (Insumo)": atualizar_estoque_direto(material, p_l, "soma")
                    elif tipo == "Saída (Massa Asfáltica)": dar_baixa_estoque_cbuq(p_l)
                    elif tipo == "Saída (Diversos)": atualizar_estoque_direto(material, p_l, "subtrai")
                    st.success("Salvo!"); st.download_button("📥 PDF", gerar_pdf_ticket(dados), f"ticket_{placa}.pdf")
                except Exception as e: st.error(f"Erro ao salvar: {e}")

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

# --- TAB 4: ALMOXARIFADO ---
with tabs[3]:
    st.header("📦 Almoxarifado")
    menu = st.radio("Ação:", ["Ver Estoque", "Lançar Movimento", "Cadastrar Novo Item"], horizontal=True)
    if menu == "Ver Estoque":
        res_alm = supabase.table("almoxarifado").select("*").execute()
        if res_alm.data: st.dataframe(pd.DataFrame(res_alm.data)[['item', 'categoria', 'quantidade', 'unidade']], use_container_width=True)
    elif menu == "Lançar Movimento":
        res_i = supabase.table("almoxarifado").select("item").execute()
        lista = [r['item'] for r in res_i.data]
        if lista:
            with st.form("mov_alm"):
                it, t_m, q_m = st.selectbox("Item", lista), st.selectbox("Tipo", ["Entrada", "Saída"]), st.number_input("Qtd", min_value=0.1)
                if st.form_submit_button("Confirmar"):
                    cur_q = supabase.table("almoxarifado").select("quantidade").eq("item", it).execute().data[0]['quantidade']
                    nova = (cur_q + q_m) if t_m == "Entrada" else (cur_q - q_m)
                    supabase.table("almoxarifado").update({"quantidade": nova}).eq("item", it).execute()
                    st.success("Atualizado!"); st.rerun()
    elif menu == "Cadastrar Novo Item":
        with st.form("n_alm"):
            ni, nc, nu = st.text_input("Item"), st.selectbox("Cat", ["Escritório", "Manutenção", "Limpeza"]), st.text_input("Unidade (Ex: Un, Cx)")
            if st.form_submit_button("Cadastrar"):
                supabase.table("almoxarifado").insert({"item": ni, "categoria": nc, "unidade": nu, "quantidade": 0}).execute()
                st.success("Cadastrado!"); st.rerun()

# --- TAB 5: MANUTENÇÃO (CORRIGIDA - LINHA 175) ---
with tabs[4]:
    st.subheader("🛠️ Diário de Manutenção")
    with st.form("f_manut"):
        mot = st.selectbox("Motivo", ["Preventiva", "Quebra", "Chuva", "Insumo"])
        c_i, c_f = st.columns(2)
        with c_i: d1 = st.date_input("Data Início"); h1 = st.time_input("Hora Início")
        with c_f: d2 = st.date_input("Data Fim"); h2 = st.time_input("Hora Fim")
        obs = st.text_area("Observações")
        if st.form_submit_button("Registrar Parada"):
            dt_inicio = datetime.combine(d1, h1)
            dt_fim = datetime.combine(d2, h2)
            tempo_h = (dt_fim - dt_inicio).total_seconds() / 3600
            if tempo_h < 0:
                st.error("Data de fim não pode ser anterior ao início.")
            else:
                # CORREÇÃO AQUI: Enviando todos os campos que o banco espera
                dados_parada = {
                    "motivo": mot, 
                    "tempo": round(tempo_h, 2),
                    "data_inicio": dt_inicio.isoformat(),
                    "data_fim": dt_fim.isoformat(),
                    "obs": obs
                }
                try:
                    supabase.table("manutencao_paradas").insert(dados_parada).execute()
                    st.success(f"Registrado com sucesso: {tempo_h:.2f} horas.")
                except Exception as e:
                    st.error(f"Erro ao salvar no banco: {e}")

# --- TAB 6: ADMIN ---
with tabs[5]:
    if st.session_state["perfil"] == "Administrador":
        st.subheader("Configurações do Sistema")
        if st.button("Resetar/Criar Tabelas de Insumos"):
            for i in ["CAP", "Pó de Brita", "Brita 0", "Brita 3/4", "Imprimante", "Cola"]:
                try: supabase.table("estoque_insumos").insert({"item": i, "quantidade_kg": 0}).execute()
                except: pass
            st.success("Estoque de insumos verificado.")