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
    pdf.set_font("Arial", "", 12)
    pdf.cell(190, 10, "COMPROVANTE DE MOVIMENTACAO DE MATERIAIS", ln=True, align="C")
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
# 3. CONTROLE DE ACESSO
# ==========================================
if "autenticado" not in st.session_state: 
    st.session_state.update({"autenticado": False, "usuario": "", "perfil": ""})

if not st.session_state["autenticado"]:
    st.title("🏛️ Sistema Usina Municipal de Vilhena")
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
st.sidebar.title(f"Operador: {st.session_state['usuario']}")
st.sidebar.button("Sair", on_click=lambda: st.session_state.update({"autenticado": False}))

tabs = st.tabs(["📊 Dashboard", "🚛 Balança", "🏗️ Traço CBUQ", "📦 Almoxarifado", "🛠️ Manutenção", "👤 Admin"])

# --- TAB 1: DASHBOARD ---
with tabs[0]:
    st.header("Estoque de Insumos (Produção)")
    res = supabase.table("estoque_insumos").select("*").execute()
    if res.data:
        df = pd.DataFrame(res.data)
        m = st.columns(len(df))
        for i, r in df.iterrows(): m[i].metric(r['item'], f"{r['quantidade_kg']:,.0f} kg")
        st.bar_chart(df.set_index("item")["quantidade_kg"])

# --- TAB 2: BALANÇA (ENTRADA/SAÍDA) ---
with tabs[1]:
    st.subheader("Registro de Pesagem")
    c1, c2 = st.columns(2)
    with c1:
        placa = st.text_input("Placa do Veículo").upper()
        motorista = st.text_input("Nome do Motorista") # Adicionado aqui
        tipo = st.selectbox("Tipo de Operação", ["Saída (Massa Asfáltica)", "Entrada (Insumo)", "Saída (Diversos)"])
        
        if tipo == "Saída (Massa Asfáltica)": 
            material, destino = "Massa Asfáltica CBUQ", st.text_input("Destino/Obra")
        elif tipo == "Entrada (Insumo)": 
            material, destino = st.selectbox("Material Insumo", ["CAP", "Pó de Brita", "Brita 0", "Brita 3/4", "Imprimante", "Cola"]), "Usina"
        else: 
            material, destino = st.text_input("Descreva o Material Diversos"), st.text_input("Destino")
        
        p_b = st.number_input("Peso Bruto (kg)", 0.0)
        p_t = st.number_input("Tara (kg)", 0.0)
        p_l = p_b - p_t
        st.info(f"Peso Líquido: {p_l} kg")
    
    with c2:
        foto = st.camera_input("Foto do Carregamento")
        if st.button("💾 Finalizar e Salvar"):
            if placa and motorista and p_l > 0:
                url_foto = ""
                if foto:
                    try: url_foto = cloudinary.uploader.upload(foto)["secure_url"]
                    except: pass
                
                dados = {
                    "placa": placa, "motorista": motorista, "tipo_movimento": tipo, 
                    "material": material, "peso_liquido": p_l, "destino": destino, 
                    "operador": st.session_state['usuario'], "foto_url": url_foto
                }
                
                try:
                    supabase.table("balanca").insert(dados).execute()
                    if tipo == "Entrada (Insumo)": atualizar_estoque_direto(material, p_l, "soma")
                    elif tipo == "Saída (Massa Asfáltica)": dar_baixa_estoque_cbuq(p_l)
                    elif tipo == "Saída (Diversos)": atualizar_estoque_direto(material, p_l, "subtrai")
                    
                    st.success("Salvo com sucesso!")
                    st.download_button("📥 Baixar PDF", gerar_pdf_ticket(dados), f"ticket_{placa}.pdf", "application/pdf")
                except Exception as e: st.error(f"Erro ao salvar: {e}")
            else: st.warning("Preencha todos os campos (Placa, Motorista e Pesos).")

# --- TAB 3: TRAÇO CBUQ ---
with tabs[2]:
    st.subheader("Configuração do Traço Atual")
    res_t = supabase.table("config_traco").select("*").execute()
    if res_t.data:
        with st.form("f_traco"):
            n_perc = {}
            for r in res_t.data: 
                n_perc[r['item']] = st.number_input(f"% de {r['item']}", 0.0, 100.0, float(r['porcentagem']))
            if st.form_submit_button("Atualizar Porcentagens"):
                for k, v in n_perc.items(): 
                    supabase.table("config_traco").update({"porcentagem": v}).eq("item", k).execute()
                st.success("Traço atualizado!"); st.rerun()

# --- TAB 4: ALMOXARIFADO (CONSUMO/ESCRITÓRIO) ---
with tabs[3]:
    st.header("📦 Gestão de Almoxarifado")
    menu_alm = st.radio("Escolha a ação:", ["Estoque Atual", "Entrada/Saída de Material", "Cadastrar Novo Item"], horizontal=True)
    
    if menu_alm == "Estoque Atual":
        res_alm = supabase.table("almoxarifado").select("*").execute()
        if res_alm.data: st.dataframe(pd.DataFrame(res_alm.data)[['item', 'categoria', 'quantidade', 'unidade']], use_container_width=True)
    
    elif menu_alm == "Entrada/Saída de Material":
        res_i = supabase.table("almoxarifado").select("item").execute()
        lista_itens = [r['item'] for r in res_i.data]
        if lista_itens:
            with st.form("mov_alm"):
                it = st.selectbox("Selecione o Material", lista_itens)
                mot = st.text_input("Motorista/Responsável")
                tm = st.selectbox("Operação", ["Entrada", "Saída"])
                qm = st.number_input("Quantidade", min_value=0.1)
                if st.form_submit_button("Confirmar Lançamento"):
                    cur = supabase.table("almoxarifado").select("quantidade").eq("item", it).execute().data[0]['quantidade']
                    nova = (cur + qm) if tm == "Entrada" else (cur - qm)
                    supabase.table("almoxarifado").update({"quantidade": nova}).eq("item", it).execute()
                    st.success("Estoque do Almoxarifado Atualizado!"); st.rerun()

    elif menu_alm == "Cadastrar Novo Item":
        with st.form("novo_alm"):
            ni = st.text_input("Nome do Material (Ex: Papel A4, Graxa, Lâmpada)")
            nc = st.selectbox("Categoria", ["Escritório", "Manutenção", "Limpeza/Consumo", "Outros"])
            nu = st.text_input("Unidade (Ex: Un, Cx, Litro, Kg)")
            if st.form_submit_button("Salvar Novo Item"):
                supabase.table("almoxarifado").insert({"item": ni, "categoria": nc, "unidade": nu, "quantidade": 0}).execute()
                st.success("Item adicionado ao Almoxarifado!"); st.rerun()

# --- TAB 5: MANUTENÇÃO (CORRIGIDA) ---
with tabs[4]:
    st.subheader("🛠️ Diário de Manutenção e Paradas")
    with st.form("f_manut"):
        motivo_p = st.selectbox("Motivo", ["Preventiva", "Quebra Mecânica", "Chuva", "Falta de Insumo/Energia"])
        c_i, c_f = st.columns(2)
        with c_i: d1 = st.date_input("Data Início"); h1 = st.time_input("Hora Início")
        with c_f: d2 = st.date_input("Data Fim"); h2 = st.time_input("Hora Fim")
        obs_p = st.text_area("Observações Técnicas")
        if st.form_submit_button("Registrar Parada da Usina"):
            dt1 = datetime.combine(d1, h1); dt2 = datetime.combine(d2, h2)
            tempo_total = (dt2 - dt1).total_seconds() / 3600
            if tempo_total < 0: st.error("A data de fim deve ser após o início.")
            else:
                d_p = {"motivo": motivo_p, "tempo": round(tempo_total, 2), "data_inicio": dt1.isoformat(), "data_fim": dt2.isoformat(), "obs": obs_p}
                try:
                    supabase.table("manutencao_paradas").insert(d_p).execute()
                    st.success(f"Registrado: {tempo_total:.2f} horas de parada.")
                except Exception as e: st.error(f"Erro no banco: {e}")

# --- TAB 6: ADMIN ---
with tabs[5]:
    if st.session_state["perfil"] == "Administrador":
        st.subheader("Painel Administrativo")
        if st.button("Sincronizar Estrutura de Insumos"):
            for i in ["CAP", "Pó de Brita", "Brita 0", "Brita 3/4", "Imprimante", "Cola"]:
                try: supabase.table("estoque_insumos").insert({"item": i, "quantidade_kg": 0}).execute()
                except: pass
            st.success("Itens de produção verificados.")