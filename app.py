import streamlit as st
import pandas as pd
from datetime import datetime
import hashlib
from supabase import create_client, Client
import cloudinary
import cloudinary.uploader
import urllib.parse

# ==========================================
# 1. CONFIGURAÇÕES E CONEXÕES
# ==========================================
st.set_page_config(page_title="Usina Municipal de Vilhena", layout="wide", page_icon="🏭")

# Tente conectar ao Supabase (Certifique-se de que os secrets estão configurados)
try:
    url: str = st.secrets["SUPABASE_URL"]
    key: str = st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(url, key)
except Exception as e:
    st.error("Erro ao conectar ao banco de dados. Verifique seus 'Secrets'.")
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
    st.warning("Cloudinary não configurado. As fotos não serão salvas.")

# ==========================================
# 2. FUNÇÕES DE SEGURANÇA E NEGÓCIO
# ==========================================
def gerar_hash_senha(senha):
    return hashlib.sha256(str.encode(senha)).hexdigest()

def verificar_senha(senha, hash_armazenado):
    return gerar_hash_senha(senha) == hash_armazenado

def garantir_admin_padrao():
    """Garante que o usuário Andre exista com a senha correta"""
    user_admin = "andre"
    senha_admin = "02152518Ab@" # Senha Corrigida
    hash_novo = gerar_hash_senha(senha_admin)
    
    try:
        res = supabase.table("usuarios").select("*").eq("usuario", user_admin).execute()
        if not res.data:
            supabase.table("usuarios").insert({
                "usuario": user_admin,
                "senha_hash": hash_novo,
                "nome": "André (Admin)",
                "perfil": "Administrador"
            }).execute()
        else:
            # Atualiza a senha caso tenha mudado no código
            supabase.table("usuarios").update({"senha_hash": hash_novo}).eq("usuario", user_admin).execute()
    except Exception as e:
        st.error(f"Erro na linha 30 (Tabela 'usuarios'): {e}")

def dar_baixa_estoque_cbuq(peso_liquido):
    """Baixa automática com traço corrigido"""
    TRACO = {
        "CAP": 0.05,            # 5%
        "Pó de Brita": 0.54,    # 54%
        "Brita 0": 0.23,        # 23%
        "Brita 3/4": 0.18       # 18%
    }
    try:
        for insumo, percentual in TRACO.items():
            qtd_consumida = peso_liquido * percentual
            res = supabase.table("estoque_insumos").select("quantidade_kg").eq("item", insumo).execute()
            if res.data:
                nova_qtd = res.data[0]['quantidade_kg'] - qtd_consumida
                supabase.table("estoque_insumos").update({"quantidade_kg": nova_qtd}).eq("item", insumo).execute()
    except Exception as e:
        st.error(f"Erro na linha 46 (Tabela 'estoque_insumos'): {e}")

# Executa a verificação do admin ao carregar o app
garantir_admin_padrao()

# ==========================================
# 3. INTERFACE (LOGIN)
# ==========================================
if "autenticado" not in st.session_state:
    st.session_state.update({"autenticado": False, "usuario": "", "nome": "", "perfil": "", "fotos_temp": []})

if not st.session_state["autenticado"]:
    st.title("🏛️ Usina Municipal de Vilhena")
    with st.form("login"):
        u = st.text_input("Usuário").lower().strip()
        p = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            res = supabase.table("usuarios").select("*").eq("usuario", u).execute()
            if res.data and verificar_senha(p, res.data[0]['senha_hash']):
                st.session_state.update({
                    "autenticado": True, "usuario": res.data[0]['usuario'], 
                    "nome": res.data[0]['nome'], "perfil": res.data[0]['perfil']
                })
                st.rerun()
            else:
                st.error("Login inválido")
    st.stop()

# ==========================================
# 4. PAINEL PRINCIPAL
# ==========================================
st.title("Usina Municipal de Vilhena")
abas = st.tabs(["📊 Dashboard", "🚛 Balança", "📈 Relatório WhatsApp", "👤 Admin"])

with abas[1]: # ABA BALANÇA
    st.subheader("Registro de Pesagem")
    col1, col2 = st.columns(2)
    with col1:
        placa = st.text_input("Placa").upper()
        tipo_mov = st.selectbox("Operação", ["Saída (Massa Asfáltica)", "Entrada (Insumo)"])
        material = st.selectbox("Material", ["Massa Asfáltica CBUQ", "CAP", "Pó de Brita", "Brita 0", "Brita 3/4", "Outros"])
        p_bruto = st.number_input("Peso Bruto (kg)", 0.0)
        p_tara = st.number_input("Tara (kg)", 0.0)
        p_liq = p_bruto - p_tara
        st.metric("Líquido", f"{p_liq} kg")
        
    with col2:
        if st.button("Finalizar Registro"):
            dados = {"placa": placa, "tipo_movimento": tipo_mov, "material": material, "peso_liquido": p_liq, "operador": st.session_state["usuario"]}
            supabase.table("balanca").insert(dados).execute()
            if tipo_mov.startswith("Saída") and material == "Massa Asfáltica CBUQ":
                dar_baixa_estoque_cbuq(p_liq)
            st.success("Salvo com sucesso!")

with abas[2]: # RELATÓRIO WHATSAPP
    if st.button("Gerar Relatório Diário"):
        hoje = datetime.now().strftime("%d/%m/%Y")
        msg = f"🏛️ *USINA MUNICIPAL DE VILHENA*\n📅 Relatório: {hoje}\nStatus: Operacional\nTraço CBUQ: 5/54/23/18"
        link = f"https://wa.me/?text={urllib.parse.quote(msg)}"
        st.markdown(f"[🟢 Enviar Relatório WhatsApp]({link})")

with abas[3]: # GESTÃO DE USUÁRIOS
    if st.session_state["perfil"] == "Administrador":
        st.subheader("Cadastrar Novo Operador")
        with st.form("novo_user"):
            n_nome = st.text_input("Nome")
            n_user = st.text_input("Login")
            n_pass = st.text_input("Senha", type="password")
            if st.form_submit_button("Criar"):
                h = gerar_hash_senha(n_pass)
                supabase.table("usuarios").insert({"usuario": n_user, "senha_hash": h, "nome": n_nome, "perfil": "Operador"}).execute()
                st.success("Criado!")