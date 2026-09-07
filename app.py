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

# Conexão Supabase
try:
    url: str = st.secrets["SUPABASE_URL"]
    key: str = st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(url, key)
except Exception as e:
    st.error("Erro de conexão com Supabase. Verifique os Secrets.")
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
    st.warning("Cloudinary não configurado corretamente.")

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
    pdf.cell(190, 10, "USINA MUNICIPAL - COMPROVANTE DE PESAGEM", ln=True, align="C")
    pdf.ln(10)
    
    pdf.set_font("Arial", "", 11)
    for k, v in dados.items():
        if k != "foto_url":
            # Remove acentos para evitar erro no FPDF simples
            txt_k = str(k).upper().replace("Í", "I").replace("Á", "A")
            txt_v = str(v).replace("Í", "I").replace("Á", "A")
            pdf.cell(50, 8, f"{txt_k}:", border=1)
            pdf.cell(140, 8, f"{txt_v}", border=1, ln=True)
    
    return pdf.output(dest="S").encode("latin-1", "replace")

def dar_baixa_estoque_cbuq(peso_liquido_kg):
    """Cálculo do Traço: CAP 5%, Pó 54%, Brita0 23%, Brita3/4 18%"""
    TRACO = {"CAP": 0.05, "Pó de Brita": 0.54, "Brita 0": 0.23, "Brita 3/4": 0.18}
    for insumo, perc in TRACO.items():
        qtd_consumida = peso_liquido_kg * perc
        res = supabase.table("estoque_insumos").select("quantidade_kg").eq("item", insumo).execute()
        if res.data:
            nova_qtd = res.data[0]['quantidade_kg'] - qtd_consumida
            supabase.table("estoque_insumos").update({"quantidade_kg": nova_qtd}).eq("item", insumo).execute()

# ==========================================
# 3. CONTROLE DE ACESSO
# ==========================================
if "autenticado" not in st.session_state:
    st.session_state.update({"autenticado": False, "usuario": "", "nome": "", "perfil": ""})

if not st.session_state["autenticado"]:
    st.title("🏛️ Sistema Usina Municipal")
    with st.form("login"):
        u_in = st.text_input("Usuário").lower().strip()
        p_in = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            try:
                res = supabase.table("usuarios").select("*").eq("usuario", u_in).execute()
                if res.data and verificar_senha(p_in, res.data[0]['senha_hash']):
                    st.session_state.update({
                        "autenticado": True, 
                        "usuario": u_in, 
                        "nome": res.data[0]['nome'], 
                        "perfil": res.data[0]['perfil']
                    })
                    st.rerun()
                else:
                    st.error("Usuário ou senha incorretos.")
            except:
                st.error("Erro ao conectar ao banco de dados.")
    st.stop()

# ==========================================
# 4. LAYOUT PRINCIPAL
# ==========================================
st.sidebar.title(f"Olá, {st.session_state['nome']}")
if st.sidebar.button("Sair"):
    st.session_state["autenticado"] = False
    st.rerun()

tabs = st.tabs(["📊 Dashboard", "🚛 Entrada/Saída", "📈 WhatsApp", "🛠️ Manutenção", "👤 Admin"])

# --- TAB 1: DASHBOARD ---
with tabs[0]:
    st.header("Status do Estoque")
    try:
        res_est = supabase.table("estoque_insumos").select("*").execute()
        if res_est.data:
            df_est = pd.DataFrame(res_est.data)
            cols = st.columns(len(df_est))
            for i, row in df_est.iterrows():
                cols[i].metric(row['item'], f"{row['quantidade_kg']:,.0f} kg")
            st.bar_chart(df_est.set_index("item")["quantidade_kg"])
    except:
        st.info("Aguardando dados de estoque...")

# --- TAB 2: ENTRADA/SAÍDA (ONDE ESTAVA O ERRO) ---
with tabs[1]:
    st.subheader("Registro de Balança")
    
    # IMPORTANTE: Criar as colunas primeiro
    col_bal_1, col_bal_2 = st.columns(2)
    
    with col_bal_1:
        placa = st.text_input("Placa do Veículo").upper()
        motorista = st.text_input("Nome do Motorista")
        tipo_op = st.selectbox("Operação", ["Saída (Massa Asfáltica)", "Entrada (Insumo)"])
        
        if "Saída" in tipo_op:
            destino = st.text_input("Destino / Obra / Rua")
            material = "Massa Asfáltica CBUQ"
        else:
            destino = "Usina"
            material = st.selectbox("Insumo Recebido", ["CAP", "Pó de Brita", "Brita 0", "Brita 3/4"])
            
        peso_bruto = st.number_input("Peso Bruto (kg)", min_value=0.0)
        tara = st.number_input("Tara Veículo (kg)", min_value=0.0)
        peso_liquido = peso_bruto - tara
        st.info(f"Peso Líquido Calculado: {peso_liquido} kg")

    with col_bal_2:
        foto = st.camera_input("Foto do Caminhão")
        
        if st.button("🚛 Finalizar e Salvar Registro"):
            if placa and peso_liquido > 0:
                with st.spinner("Processando..."):
                    url_foto = ""
                    # Upload para Cloudinary
                    if foto is not None:
                        try:
                            upload = cloudinary.uploader.upload(foto)
                            url_foto = upload["secure_url"]
                        except:
                            st.warning("Falha no upload da imagem, salvando apenas dados.")

                    # Salvar no Supabase
                    dados_salvar = {
                        "placa": placa,
                        "motorista": motorista,
                        "tipo_movimento": tipo_op,
                        "material": material,
                        "peso_liquido": peso_liquido,
                        "destino": destino,
                        "operador": st.session_state['usuario'],
                        "foto_url": url_foto
                    }
                    
                    try:
                        supabase.table("balanca").insert(dados_salvar).execute()
                        
                        # Baixa de estoque automática
                        if "Saída" in tipo_op:
                            dar_baixa_estoque_cbuq(peso_liquido)
                        
                        st.success("Registro concluído!")
                        
                        # Gerar PDF para Download
                        pdf_data = gerar_pdf_ticket(dados_salvar)
                        st.download_button("📥 Baixar Comprovante (PDF)", pdf_data, f"ticket_{placa}.pdf", "application/pdf")
                    except Exception as e:
                        st.error(f"Erro ao salvar: {e}")
            else:
                st.error("Preencha a placa e os pesos corretamente.")

# --- TAB 3: WHATSAPP ---
with tabs[2]:
    st.subheader("Relatório Diário")
    msg = f"🏛️ *USINA MUNICIPAL DE VILHENA*\n📅 Data: {datetime.now().strftime('%d/%m/%Y')}\nStatus: Operacional"
    link = f"https://wa.me/?text={urllib.parse.quote(msg)}"
    st.markdown(f"[🟢 Enviar Relatório via WhatsApp]({link})")

# --- TAB 4: MANUTENÇÃO ---
with tabs[3]:
    st.subheader("Diário de Paradas")
    with st.form("parada"):
        motivo = st.selectbox("Motivo", ["Manutenção Preventiva", "Quebra Mecânica", "Falta de Insumo", "Chuva"])
        horas = st.number_input("Tempo Parado (Horas)", 0.0)
        obs = st.text_area("Observações")
        if st.form_submit_button("Registrar Parada"):
            supabase.table("manutencao_paradas").insert({"motivo": motivo, "tempo": horas, "obs": obs}).execute()
            st.success("Registrado com sucesso.")

# --- TAB 5: ADMIN ---
with tabs[4]:
    if st.session_state["perfil"] == "Administrador":
        st.subheader("Cadastrar Novo Operador")
        with st.form("novo_user"):
            new_u = st.text_input("Usuário (Login)")
            new_n = st.text_input("Nome Completo")
            new_s = st.text_input("Senha", type="password")
            if st.form_submit_button("Criar Conta"):
                h = gerar_hash_senha(new_s)
                supabase.table("usuarios").insert({"usuario": new_u, "senha_hash": h, "nome": new_n, "perfil": "Operador"}).execute()
                st.success(f"Usuário {new_u} criado!")
    else:
        st.warning("Apenas administradores podem acessar esta aba.")