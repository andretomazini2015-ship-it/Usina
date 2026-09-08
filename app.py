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
            pdf.cell(60, 8, f"{str(k).upper().replace('_', ' ')}:", border=1)
            pdf.cell(130, 8, f"{str(v)}", border=1, ln=True)
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
# 3. CONTROLE DE LOGIN
# ==========================================
if "autenticado" not in st.session_state:
    st.session_state.update({"autenticado": False, "usuario": "", "nome": "", "perfil": ""})

if not st.session_state["autenticado"]:
    st.title("🏛️ Sistema de Gestão - Usina Municipal")
    with st.form("login"):
        u = st.text_input("Usuário").lower().strip()
        p = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            res = supabase.table("usuarios").select("*").eq("usuario", u).execute()
            if res.data and verificar_senha(p, res.data[0]['senha_hash']):
                st.session_state.update({
                    "autenticado": True, "usuario": u, 
                    "nome": res.data[0]['nome'], "perfil": res.data[0]['perfil']
                })
                st.rerun()
            else: st.error("Usuário ou senha inválidos.")
    st.stop()

# ==========================================
# 4. MENU LATERAL E FILTRO DE ABAS
# ==========================================
st.sidebar.title(f"👤 {st.session_state['nome']}")
st.sidebar.info(f"Perfil: {st.session_state['perfil']}")
if st.sidebar.button("Sair"):
    st.session_state.update({"autenticado": False})
    st.rerun()

# --- DEFINIÇÃO DE ACESSOS ---
perfis_acesso = {
    "Administrador": ["📊 Dashboard", "🚛 Balança", "🏗️ Traço CBUQ", "📦 Almoxarifado", "🛠️ Manutenção", "📈 WhatsApp", "👥 Usuários"],
    "Operador Balança": ["📊 Dashboard", "🚛 Balança", "📈 WhatsApp"],
    "Gestor Almoxarifado/Manutenção": ["📊 Dashboard", "📦 Almoxarifado", "🛠️ Manutenção", "📈 WhatsApp"]
}

abas_disponiveis = perfis_acesso.get(st.session_state["perfil"], ["📊 Dashboard"])
tabs = st.tabs(abas_disponiveis)
tab_map = {nome: tabs[i] for i, nome in enumerate(abas_disponiveis)}

# --- TAB: DASHBOARD ---
if "📊 Dashboard" in tab_map:
    with tab_map["📊 Dashboard"]:
        st.header("Estoque Geral de Insumos")
        res = supabase.table("estoque_insumos").select("*").execute()
        if res.data:
            df = pd.DataFrame(res.data)
            m = st.columns(len(df))
            for i, r in df.iterrows(): m[i].metric(r['item'], f"{r['quantidade_kg']:,.0f} kg")
            st.bar_chart(df.set_index("item")["quantidade_kg"])

# --- TAB: BALANÇA ---
if "🚛 Balança" in tab_map:
    with tab_map["🚛 Balança"]:
        st.subheader("Registro de Pesagem")
        c1, c2 = st.columns(2)
        with c1:
            pl = st.text_input("Placa").upper()
            mot = st.text_input("Motorista")
            tipo = st.selectbox("Operação", ["Saída (Massa Asfáltica)", "Entrada (Insumo)", "Saída (Diversos)"])
            if tipo == "Saída (Massa Asfáltica)": material, destino = "Massa Asfáltica CBUQ", st.text_input("Destino/Obra")
            elif tipo == "Entrada (Insumo)": material, destino = st.selectbox("Insumo", ["CAP", "Pó de Brita", "Brita 0", "Brita 3/4", "Imprimante", "Cola"]), "Usina"
            else: material, destino = st.text_input("Material Diversos"), st.text_input("Destino")
            p_l = st.number_input("Peso Líquido (kg)", 0.0)
        with c2:
            foto = st.camera_input("Foto")
            if st.button("💾 Salvar Registro"):
                if pl and mot and p_l > 0:
                    dados = {"placa": pl, "motorista": mot, "tipo_movimento": tipo, "material": material, "peso_liquido": p_l, "destino": destino, "operador": st.session_state['usuario']}
                    try:
                        supabase.table("balanca").insert(dados).execute()
                        if tipo == "Entrada (Insumo)": atualizar_estoque_direto(material, p_l, "soma")
                        elif tipo == "Saída (Massa Asfáltica)": dar_baixa_estoque_cbuq(p_l)
                        elif tipo == "Saída (Diversos)": atualizar_estoque_direto(material, p_l, "subtrai")
                        st.success("Salvo!"); st.download_button("📥 PDF", gerar_pdf_ticket(dados), f"ticket_{pl}.pdf")
                    except Exception as e: st.error(f"Erro: {e}")

# --- TAB: TRAÇO CBUQ ---
if "🏗️ Traço CBUQ" in tab_map:
    with tab_map["🏗️ Traço CBUQ"]:
        st.subheader("Configuração do Traço")
        res_t = supabase.table("config_traco").select("*").execute()
        if res_t.data:
            with st.form("f_traco"):
                n_p = {r['item']: st.number_input(f"% {r['item']}", 0.0, 100.0, float(r['porcentagem'])) for r in res_t.data}
                if st.form_submit_button("Salvar Traço"):
                    for k, v in n_p.items(): supabase.table("config_traco").update({"porcentagem": v}).eq("item", k).execute()
                    st.success("Traço atualizado!"); st.rerun()

# --- TAB: ALMOXARIFADO ---
if "📦 Almoxarifado" in tab_map:
    with tab_map["📦 Almoxarifado"]:
        st.header("Gestão de Almoxarifado")
        m_alm = st.radio("Ação:", ["Estoque", "Lançar Movimento", "Novo Item"], horizontal=True)
        if m_alm == "Estoque":
            res = supabase.table("almoxarifado").select("*").execute()
            if res.data: st.dataframe(pd.DataFrame(res.data)[['item', 'categoria', 'quantidade', 'unidade']], use_container_width=True)
        elif m_alm == "Lançar Movimento":
            itens_res = supabase.table("almoxarifado").select("item").execute()
            itens = [r['item'] for r in itens_res.data]
            with st.form("f_mov"):
                it, tm, qm = st.selectbox("Item", itens), st.selectbox("Tipo", ["Entrada", "Saída"]), st.number_input("Qtd", 0.1)
                if st.form_submit_button("Confirmar"):
                    cur = supabase.table("almoxarifado").select("quantidade").eq("item", it).execute().data[0]['quantidade']
                    nova = (cur + qm) if tm == "Entrada" else (cur - qm)
                    supabase.table("almoxarifado").update({"quantidade": nova}).eq("item", it).execute()
                    st.success("Atualizado!"); st.rerun()
        elif m_alm == "Novo Item":
            with st.form("f_ni"):
                ni, nc, nu = st.text_input("Item"), st.selectbox("Cat", ["Escritório", "Manutenção", "Limpeza"]), st.text_input("Unidade")
                if st.form_submit_button("Cadastrar"):
                    supabase.table("almoxarifado").insert({"item": ni, "categoria": nc, "unidade": nu, "quantidade": 0}).execute()
                    st.success("Item Criado!"); st.rerun()

# --- TAB: MANUTENÇÃO ---
if "🛠️ Manutenção" in tab_map:
    with tab_map["🛠️ Manutenção"]:
        st.subheader("Diário de Paradas")
        with st.form("f_manut"):
            mot = st.selectbox("Motivo", ["Preventiva", "Quebra", "Chuva", "Insumo"])
            d1, h1 = st.date_input("Início"), st.time_input("Hora Início")
            d2, h2 = st.date_input("Fim"), st.time_input("Hora Fim")
            if st.form_submit_button("Registrar Parada"):
                t = (datetime.combine(d2, h2) - datetime.combine(d1, h1)).total_seconds() / 3600
                dados_m = {"motivo": mot, "tempo": round(t, 2), "data_inicio": datetime.combine(d1, h1).isoformat(), "data_fim": datetime.combine(d2, h2).isoformat()}
                supabase.table("manutencao_paradas").insert(dados_m).execute()
                st.success(f"Registrado {t:.2f}h"); st.rerun()

# --- TAB: WHATSAPP (RECOLOCADA) ---
if "📈 WhatsApp" in tab_map:
    with tab_map["📈 WhatsApp"]:
        st.header("Relatório Rápido")
        st.write("Gere um resumo para enviar ao grupo da Secretaria de Obras.")
        data_hj = datetime.now().strftime('%d/%m/%Y')
        resumo = f"🏛️ *USINA MUNICIPAL DE VILHENA*\n📅 Relatório Diário: {data_hj}\n\n"
        
        # Puxa estoque para o resumo
        res_e = supabase.table("estoque_insumos").select("*").execute()
        if res_e.data:
            resumo += "*Estoque de Insumos:*\n"
            for r in res_e.data:
                resumo += f"• {r['item']}: {r['quantidade_kg']:,.0f} kg\n"
        
        resumo += "\nStatus: Operacional ✅"
        
        st.text_area("Prévia da Mensagem:", resumo, height=200)
        
        link = f"https://wa.me/?text={urllib.parse.quote(resumo)}"
        st.markdown(f"[🟢 Clique aqui para enviar via WhatsApp]({link})")

# --- TAB: USUÁRIOS (ADMIN ONLY) ---
if "👥 Usuários" in tab_map:
    with tab_map["👥 Usuários"]:
        st.header("Gestão de Usuários")
        res_u = supabase.table("usuarios").select("usuario, nome, perfil").execute()
        if res_u.data: st.table(pd.DataFrame(res_u.data))
        
        with st.form("f_novo_u"):
            new_u = st.text_input("Login").lower().strip()
            new_n = st.text_input("Nome")
            new_p = st.selectbox("Perfil", ["Operador Balança", "Gestor Almoxarifado/Manutenção", "Administrador"])
            new_s = st.text_input("Senha Inicial", type="password")
            if st.form_submit_button("Cadastrar Usuário"):
                h = gerar_hash_senha(new_s)
                supabase.table("usuarios").insert({"usuario": new_u, "senha_hash": h, "nome": new_n, "perfil": new_p}).execute()
                st.success("Cadastrado!"); st.rerun()