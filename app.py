import streamlit as st
import pandas as pd
from datetime import datetime
import hashlib
import io
from PIL import Image
from fpdf import FPDF
from supabase import create_client, Client
import cloudinary
import cloudinary.uploader
import urllib.parse

# ==========================================
# CONFIGURAÇÕES E CONEXÕES (CLOUD)
# ==========================================
st.set_page_config(page_title="Usina Digital Cloud", layout="wide", page_icon="🏭")

# Conexão Supabase
url: str = st.secrets["SUPABASE_URL"]
key: str = st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(url, key)

# Conexão Cloudinary
cloudinary.config(
  cloud_name = st.secrets["CLOUDINARY_NAME"],
  api_key = st.secrets["CLOUDINARY_KEY"],
  api_secret = st.secrets["CLOUDINARY_SECRET"],
  secure = True
)

# ==========================================
# FUNÇÕES DE SEGURANÇA
# ==========================================
def gerar_hash_senha(senha):
    return hashlib.sha256(str.encode(senha)).hexdigest()

def verificar_senha(senha, hash_armazenado):
    return gerar_hash_senha(senha) == hash_armazenado

# ==========================================
# LÓGICA DE NEGÓCIO E CLOUD UPLOAD
# ==========================================
def upload_foto_cloudinary(foto_bytes):
    """Sobe a imagem para o Cloudinary e retorna a URL"""
    try:
        upload_result = cloudinary.uploader.upload(foto_bytes)
        return upload_result["secure_url"]
    except Exception as e:
        st.error(f"Erro no upload da imagem: {e}")
        return None

def dar_baixa_estoque_cbuq(peso_liquido):
    TRACO = {"Brita 0": 0.45, "Brita 3/4": 0.25, "Pó de Brita": 0.24, "CAP": 0.05, "Imprimante": 0.005, "Cola": 0.005}
    for insumo, percentual in TRACO.items():
        qtd_consumida = peso_liquido * percentual
        # No Supabase, fazemos o update baseado na quantidade atual
        res = supabase.table("estoque_insumos").select("quantidade_kg").eq("item", insumo).execute()
        if res.data:
            nova_qtd = res.data[0]['quantidade_kg'] - qtd_consumida
            supabase.table("estoque_insumos").update({"quantidade_kg": nova_qtd}).eq("item", insumo).execute()

# ==========================================
# TELA DE LOGIN
# ==========================================
if "autenticado" not in st.session_state:
    st.session_state.update({"autenticado": False, "usuario": "", "nome": "", "perfil": "", "fotos_temp": []})

if not st.session_state["autenticado"]:
    st.title("🏭 Acesso Usina Digital")
    with st.form("login"):
        user_input = st.text_input("Usuário")
        pass_input = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            res = supabase.table("usuarios").select("*").eq("usuario", user_input.lower()).execute()
            if res.data and verificar_senha(pass_input, res.data[0]['senha_hash']):
                st.session_state.update({
                    "autenticado": True, "usuario": res.data[0]['usuario'], 
                    "nome": res.data[0]['nome'], "perfil": res.data[0]['perfil']
                })
                st.rerun()
            else:
                st.error("Usuário ou senha incorretos")
    st.stop()

# ==========================================
# INTERFACE PRINCIPAL
# ==========================================
aba_nomes = ["📊 Visão Geral", "🚛 Balança", "📈 Relatórios", "⚙️ Manutenção"]
if st.session_state["perfil"] == "Administrador":
    aba_nomes.append("👤 Admin")

abas = st.tabs(aba_nomes)

# --- ABA BALANÇA ---
with abas[1]:
    col1, col2 = st.columns(2)
    with col1:
        placa = st.text_input("Placa").upper()
        motorista = st.text_input("Motorista")
        tipo_mov = st.selectbox("Operação", ["Saída (Massa Asfáltica)", "Entrada (Insumo)"])
        material = st.selectbox("Material", ["Massa Asfáltica CBUQ", "Brita 0", "Brita 3/4", "Pó de Brita", "CAP", "Imprimante", "Cola"])
        temp = st.number_input("Temperatura (°C)", value=150)
        p_bruto = st.number_input("Peso Bruto (kg)", min_value=0.0)
        p_tara = st.number_input("Tara (kg)", min_value=0.0)
        p_liquido = max(0.0, p_bruto - p_tara)
        st.info(f"Peso Líquido: {p_liquido} kg")

    with col2:
        foto = st.camera_input("Capturar Foto")
        if foto and st.button("Adicionar Foto"):
            st.session_state["fotos_temp"].append(foto.getvalue())
            st.success("Foto adicionada!")

        if st.button("Finalizar e Salvar", type="primary"):
            urls_fotos = []
            for f_bytes in st.session_state["fotos_temp"]:
                url_f = upload_foto_cloudinary(f_bytes)
                if url_f: urls_fotos.append(url_f)
            
            dados = {
                "placa": placa, "motorista": motorista, "tipo_movimento": tipo_mov,
                "material": material, "peso_bruto": p_bruto, "tara": p_tara,
                "peso_liquido": p_liquido, "foto_path": ",".join(urls_fotos),
                "operador": st.session_state["usuario"], "temperatura": temp
            }
            
            supabase.table("balanca").insert(dados).execute()
            
            if tipo_mov.startswith("Saída"):
                dar_baixa_estoque_cbuq(p_liquido)
            
            st.session_state["fotos_temp"] = []
            st.success("Registro Salvo na Nuvem!")

# --- ABA RELATÓRIOS ---
with abas[2]:
    st.subheader("Histórico de Pesagens")
    res = supabase.table("balanca").select("*").order("id", desc=True).execute()
    if res.data:
        df = pd.DataFrame(res.data)
        st.dataframe(df)
        
        for r in res.data:
            with st.expander(f"Ticket {r['id']} - {r['placa']}"):
                if r['foto_path']:
                    for url_f in r['foto_path'].split(','):
                        st.image(url_f, width=200)

# (Adicione aqui as outras abas seguindo a lógica do supabase.table...)