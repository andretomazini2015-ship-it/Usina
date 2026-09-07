import streamlit as st
import pandas as pd
from datetime import datetime
import hashlib
import urllib.parse
import io
from fpdf import FPDF
from supabase import create_client, Client
import cloudinary
import cloudinary.uploader

# ==========================================
# 1. CONFIGURAÇÕES E CONEXÕES
# ==========================================
st.set_page_config(page_title="Usina Municipal de Vilhena", layout="wide", page_icon="🏭")

# Conexão Supabase
try:
    url: str = st.secrets["SUPABASE_URL"]
    key: str = st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(url, key)
except Exception as e:
    st.error(f"Erro de conexão com Supabase: {e}. Verifique os Secrets.")
    st.stop()

# Conexão Cloudinary
try:
    cloudinary.config(
      cloud_name = st.secrets["CLOUDINARY_NAME"],
      api_key = st.secrets["CLOUDINARY_KEY"],
      api_secret = st.secrets["CLOUDINARY_SECRET"],
      secure = True
    )
except:
    st.warning("Cloudinary não configurado. As fotos não serão processadas.")

# ==========================================
# 2. FUNÇÕES DE APOIO E SEGURANÇA
# ==========================================
def gerar_hash_senha(senha):
    return hashlib.sha256(str.encode(senha)).hexdigest()

def verificar_senha(senha, hash_armazenado):
    return gerar_hash_senha(senha) == hash_armazenado

def sincronizar_usuarios_padrao():
    """Garante usuários mestres no sistema"""
    usuarios = [
        {"u": "andre", "s": "02152518Ab@", "n": "André (Admin)", "p": "Administrador"},
        {"u": "usina", "s": "123", "n": "Operador Usina", "p": "Operador"}
    ]
    for user in usuarios:
        h = gerar_hash_senha(user["s"])
        try:
            res = supabase.table("usuarios").select("*").eq("usuario", user["u"]).execute()
            if not res.data:
                supabase.table("usuarios").insert({"usuario": user["u"], "senha_hash": h, "nome": user["n"], "perfil": user["p"]}).execute()
            else:
                supabase.table("usuarios").update({"senha_hash": h}).eq("usuario", user["u"]).execute()
        except: pass

def gerar_pdf_ticket(dados):
    """MODIFICAÇÃO 2: Gerador de Comprovante PDF"""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(190, 10, "PREFEITURA MUNICIPAL DE VILHENA", ln=True, align="C")
    pdf.set_font("Arial", "", 12)
    pdf.cell(190, 10, "USINA MUNICIPAL - COMPROVANTE DE PESAGEM", ln=True, align="C")
    pdf.ln(10)
    pdf.set_font("Arial", "", 11)
    for k, v in dados.items():
        if k != "foto_path":
            pdf.cell(50, 8, f"{k.upper()}:", border=1)
            pdf.cell(140, 8, f"{v}", border=1, ln=True)
    return pdf.output(dest="S").encode("latin-1")

def dar_baixa_estoque_cbuq(peso_liquido):
    """Cálculo do Traço: CAP 5%, Pó 54%, Brita0 23%, Brita3/4 18%"""
    TRACO = {"CAP": 0.05, "Pó de Brita": 0.54, "Brita 0": 0.23, "Brita 3/4": 0.18}
    for insumo, perc in TRACO.items():
        qtd_consumida = peso_liquido * perc
        res = supabase.table("estoque_insumos").select("quantidade_kg").eq("item", insumo).execute()
        if res.data:
            nova_qtd = res.data[0]['quantidade_kg'] - qtd_consumida
            supabase.table("estoque_insumos").update({"quantidade_kg": nova_qtd}).eq("item", insumo).execute()

# Inicialização
sincronizar_usuarios_padrao()

# ==========================================
# 3. CONTROLE DE ACESSO
# ==========================================
if "autenticado" not in st.session_state:
    st.session_state.update({"autenticado": False, "usuario": "", "nome": "", "perfil": "", "fotos_temp": []})

if not st.session_state["autenticado"]:
    st.title("🏛️ Usina Municipal de Vilhena")
    with st.form("login"):
        u_in = st.text_input("Usuário").lower().strip()
        p_in = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            res = supabase.table("usuarios").select("*").eq("usuario", u_in).execute()
            if res.data and verificar_senha(p_in, res.data[0]['senha_hash']):
                st.session_state.update({"autenticado": True, "usuario": u_in, "nome": res.data[0]['nome'], "perfil": res.data[0]['perfil']})
                st.rerun()
            else: st.error("Acesso Negado.")
    st.stop()

# ==========================================
# 4. APLICATIVO PRINCIPAL
# ==========================================
st.sidebar.image("https://i.imgur.com/8Yv9XkS.png", width=150) # Espaço para logo
st.sidebar.title(f"Olá, {st.session_state['nome']}")
if st.sidebar.button("Sair"):
    st.session_state["autenticado"] = False
    st.rerun()

tabs = st.tabs(["📊 Dashboard", "🚛 Entrada/Saida", "📈 WhatsApp", "🛠️ Manutenção/Almoxarifado", "👤 Admin"])

# --- TAB 1: DASHBOARD (MODIFICAÇÃO 4: ALERTAS) ---
with tabs[0]:
    st.header("Painel de Controle Usina")
    try:
        res_est = supabase.table("estoque_insumos").select("*").execute()
        if res_est.data:
            # Alertas Críticos
            for r in res_est.data:
                if r['quantidade_kg'] < 3000:
                    st.error(f"🚨 **ALERTA CRÍTICO:** Estoque de {r['item']} abaixo de 3.000kg!")
            
            # Métricas Visuais
            m = st.columns(len(res_est.data))
            for i, r in enumerate(res_est.data):
                m[i].metric(r['item'], f"{r['quantidade_kg']:,.0f} kg")
            st.bar_chart(pd.DataFrame(res_est.data).set_index("item")["quantidade_kg"])
    except: st.info("Sem dados de estoque.")

# --- TAB 2: ENTRADA/SAIDA (MODIFICAÇÃO 1: DESTINO | MODIFICAÇÃO 2: PDF) ---
with tabs[1]:
    st.subheader("Registro de Balança")
    c1, c2 = st.columns(2)
    with c1:
        placa = st.text_input("Placa").upper()
        motorista = st.text_input("Motorista")
        tipo_op = st.selectbox("Operação", ["Saída (Massa Asfáltica)", "Entrada (Insumo)"])
        
        # Destino (Modificação 1)
        destino = st.text_input("Destino/Obra/Rua") if "Saída" in tipo_op else "Usina"
        mat = st.selectbox("Material", ["Massa Asfáltica CBUQ", "CAP", "Pó de Brita", "Brita 0", "Brita 3/4"]) if "Entrada" in tipo_op else "Massa Asfáltica CBUQ"
        
        p_b = st.number_input("Peso Bruto (kg)", 0.0)
        p_t = st.number_input("Tara (kg)", 0.0)
        p_l = p_b - p_t
        st.metric("Peso Líquido", f"{p_l} kg")

    with c2:
        foto = st.camera_input("Foto do Carregamento")
        if st.button("Finalizar Registro"):
            if p_l > 0 and placa:
                dados = {"placa": placa, "motorista": motorista, "tipo_movimento": tipo_op, "material": mat, "peso_liquido": p_l, "destino": destino, "operador": st.session_state['usuario']}
                supabase.table("balanca").insert(dados).execute()
                if "Saída" in tipo_op and mat == "Massa Asfáltica CBUQ": dar_baixa_estoque_cbuq(p_l)
                
                pdf = gerar_pdf_ticket(dados)
                st.download_button("📥 Baixar Ticket Comprovante", pdf, f"ticket_{placa}.pdf")
                st.success("Salvo com sucesso!")
            else: st.warning("Verifique os dados.")

# --- TAB 3: WHATSAPP ---
with tabs[2]:
    st.subheader("Enviar Relatório Diário")
    if st.button("Gerar Link WhatsApp"):
        texto = f"🏛️ *USINA MUNICIPAL DE VILHENA*\n📅 Relatório: {datetime.now().strftime('%d/%m/%Y')}\nStatus: Operacional"
        st.markdown(f"[🟢 Clique aqui para enviar](https://wa.me/?text={urllib.parse.quote(texto)})")

# --- TAB 4: MANUTENÇÃO (MODIFICAÇÃO 3: DIÁRIO DE PARADAS) ---
with tabs[3]:
    st.subheader("🛠️ Diário de Manutenção e Almoxarifado")
    with st.form("parada"):
        motivo = st.selectbox("Motivo da Parada", ["Preventiva", "Quebra", "Chuva", "Falta Insumo"])
        tempo = st.number_input("Horas Parado", 0.0)
        obs = st.text_area("Notas Técnicas")
        if st.form_submit_button("Registrar Evento"):
            supabase.table("manutencao_paradas").insert({"motivo": motivo, "tempo": tempo, "obs": obs}).execute()
            st.success("Registrado.")

# --- TAB 5: ADMIN ---
with tabs[4]:
    if st.session_state["perfil"] == "Administrador":
        st.subheader("Gestão de Operadores")
        with st.form("novo_u"):
            n_u = st.text_input("Novo Usuário").lower()
            n_s = st.text_input("Senha Temp", type="password")
            if st.form_submit_button("Criar"):
                h = gerar_hash_senha(n_s)
                supabase.table("usuarios").insert({"usuario": n_u, "senha_hash": h, "perfil": "Operador", "nome": n_u}).execute()
                st.success("Criado!")
    else: st.warning("Acesso restrito ao Administrador.")