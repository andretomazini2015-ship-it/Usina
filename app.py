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
    st.warning("Cloudinary não configurado. As fotos não serão processadas.")

# ==========================================
# 2. FUNÇÕES DE APOIO
# ==========================================
def gerar_hash_senha(senha):
    return hashlib.sha256(str.encode(senha)).hexdigest()

def verificar_senha(senha, hash_armazenado):
    return gerar_hash_senha(senha) == hash_armazenado

def gerar_pdf_ticket(dados):
    """Gera o comprovante em PDF tratando erros de codificação e bytes"""
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
            # Limpa acentos para evitar erro no FPDF
            txt_k = str(k).upper().replace("Í", "I").replace("Á", "A").replace("Õ", "O").replace("Ç", "C").replace("É", "E")
            txt_v = str(v).replace("Í", "I").replace("Á", "A").replace("Õ", "O").replace("Ç", "C").replace("É", "E")
            pdf.cell(50, 8, f"{txt_k}:", border=1)
            pdf.cell(140, 8, f"{txt_v}", border=1, ln=True)
    
    # Captura a saída do PDF
    resultado = pdf.output(dest="S")
    
    # CORREÇÃO DO ERRO 'bytearray' object has no attribute 'encode'
    if isinstance(resultado, (bytes, bytearray)):
        return bytes(resultado) # Já está em bytes, apenas garante o formato
    return resultado.encode("latin-1", "replace") # Se for string, encoda

def dar_baixa_estoque_cbuq(peso_liquido_kg):
    """Cálculo do Traço e Baixa no Banco"""
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
            except Exception as e:
                st.error(f"Erro ao conectar: {e}")
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
    st.header("Status do Estoque de Insumos")
    try:
        res_est = supabase.table("estoque_insumos").select("*").execute()
        if res_est.data and len(res_est.data) > 0:
            df_est = pd.DataFrame(res_est.data)
            
            # Métricas
            cols_m = st.columns(len(df_est))
            for i, row in df_est.iterrows():
                cols_m[i].metric(row['item'], f"{row['quantidade_kg']:,.0f} kg")
            
            # Gráfico
            st.bar_chart(df_est.set_index("item")["quantidade_kg"])
        else:
            st.warning("Estoque não encontrado. Vá em Admin ou rode o SQL de inicialização.")
            if st.button("Criar Estoque Inicial"):
                itens = [
                    {"item": "CAP", "quantidade_kg": 10000},
                    {"item": "Pó de Brita", "quantidade_kg": 50000},
                    {"item": "Brita 0", "quantidade_kg": 50000},
                    {"item": "Brita 3/4", "quantidade_kg": 50000}
                ]
                supabase.table("estoque_insumos").insert(itens).execute()
                st.rerun()
    except Exception as e:
        st.error(f"Erro ao carregar dados: {e}")

# --- TAB 2: ENTRADA/SAÍDA ---
with tabs[1]:
    st.subheader("Registro de Balança")
    
    # Define as colunas antes de usá-las
    col1, col2 = st.columns(2)
    
    with col1:
        placa = st.text_input("Placa").upper()
        motorista = st.text_input("Motorista")
        tipo_op = st.selectbox("Operação", ["Saída (Massa Asfáltica)", "Entrada (Insumo)"])
        
        if "Saída" in tipo_op:
            destino = st.text_input("Destino / Obra")
            material = "Massa Asfáltica CBUQ"
        else:
            destino = "Usina"
            material = st.selectbox("Insumo", ["CAP", "Pó de Brita", "Brita 0", "Brita 3/4"])
            
        p_bruto = st.number_input("Peso Bruto (kg)", 0.0)
        tara = st.number_input("Tara (kg)", 0.0)
        p_liquido = p_bruto - tara
        st.metric("Peso Líquido", f"{p_liquido} kg")

    with col2:
        foto = st.camera_input("Foto do Carregamento")
        
        if st.button("💾 Finalizar Registro"):
            if placa and p_liquido > 0:
                with st.spinner("Salvando..."):
                    url_foto = ""
                    if foto:
                        try:
                            up = cloudinary.uploader.upload(foto)
                            url_foto = up["secure_url"]
                        except: pass

                    dados_registro = {
                        "placa": placa,
                        "motorista": motorista,
                        "tipo_movimento": tipo_op,
                        "material": material,
                        "peso_liquido": p_liquido,
                        "destino": destino,
                        "operador": st.session_state['usuario'],
                        "foto_url": url_foto
                    }
                    
                    try:
                        # 1. Salva no Banco
                        supabase.table("balanca").insert(dados_registro).execute()
                        
                        # 2. Baixa estoque se for saída
                        if "Saída" in tipo_op:
                            dar_baixa_estoque_cbuq(p_liquido)
                        
                        st.success("✅ Registro salvo com sucesso!")
                        
                        # 3. PDF
                        pdf_bytes = gerar_pdf_ticket(dados_registro)
                        st.download_button("📥 Baixar Comprovante", pdf_bytes, f"ticket_{placa}.pdf", "application/pdf")
                    
                    except Exception as e:
                        st.error(f"Erro ao salvar: {e}")
            else:
                st.warning("Verifique se a placa e os pesos estão corretos.")

# --- TAB 3: WHATSAPP ---
with tabs[2]:
    st.subheader("Relatórios")
    texto = f"🏛️ *USINA VILHENA* - Relatório {datetime.now().strftime('%d/%m/%Y')}"
    st.markdown(f"[🟢 Enviar Status via WhatsApp](https://wa.me/?text={urllib.parse.quote(texto)})")

# --- TAB 4: MANUTENÇÃO ---
with tabs[3]:
    st.subheader("Registro de Paradas")
    with st.form("parada"):
        mot = st.selectbox("Motivo", ["Chuva", "Quebra", "Manutenção", "Falta Insumo"])
        tempo = st.number_input("Horas", 0.0)
        if st.form_submit_button("Registrar"):
            supabase.table("manutencao_paradas").insert({"motivo": mot, "tempo": tempo}).execute()
            st.success("OK")

# --- TAB 5: ADMIN ---
with tabs[4]:
    if st.session_state["perfil"] == "Administrador":
        st.subheader("Gestão de Usuários")
        with st.form("add_user"):
            new_u = st.text_input("Login")
            new_n = st.text_input("Nome")
            new_s = st.text_input("Senha", type="password")
            if st.form_submit_button("Cadastrar Operador"):
                h = gerar_hash_senha(new_s)
                supabase.table("usuarios").insert({"usuario": new_u, "senha_hash": h, "nome": new_n, "perfil": "Operador"}).execute()
                st.success("Criado!")
    else:
        st.warning("Acesso restrito.")