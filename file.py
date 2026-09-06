import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime
import os
from PIL import Image
import io
import hashlib

# Tentar importar serial para comunicação com balança
try:
    import serial
    SERIAL_DISPONIVEL = True
except ImportError:
    SERIAL_DISPONIVEL = False

# ==========================================
# FUNÇÕES DE SEGURANÇA E CRIPTOGRAFIA
# ==========================================
def gerhar_hash_senha(senha):
    """Gera um hash SHA-256 seguro para a senha."""
    return hashlib.sha256(str.encode(senha)).hexdigest()

def verificar_senha(senha, hash_armazenado):
    return gerhar_hash_senha(senha) == hash_armazenado

# ==========================================
# CONFIGURAÇÃO DO BANCO DE DADOS
# ==========================================
conn = sqlite3.connect("usina_asfalto.db", check_same_thread=False)
cursor = conn.cursor()

# Tabela de Usuários com Perfil de Acesso
cursor.execute("""
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario TEXT UNIQUE NOT NULL,
    senha_hash TEXT NOT NULL,
    nome TEXT NOT NULL,
    perfil TEXT CHECK(perfil IN ('Administrador', 'Colaborador')) NOT NULL
)
""")

# ==========================================
# USUÁRIOS PRÉ-CADASTRADOS (OPÇÃO 2)
# ==========================================
usuarios_iniciais = [
    ("andre", gerhar_hash_senha("02152518Ab@"), "André", "Administrador"),
    ("usina", gerhar_hash_senha("123"), "Usina", "Colaborador")
]

for usr, pwd_hash, nome, perfil in usuarios_iniciais:
    cursor.execute("""
        INSERT OR IGNORE INTO usuarios (usuario, senha_hash, nome, perfil)
        VALUES (?, ?, ?, ?)
    """, (usr, pwd_hash, nome, perfil))

# Demais Tabelas do Sistema
cursor.execute("""
CREATE TABLE IF NOT EXISTS balanca (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    placa TEXT, motorista TEXT, tipo_movimento TEXT, material TEXT,
    peso_bruto REAL, tara REAL, peso_liquido REAL,
    data_hora TEXT, foto_path TEXT, operador TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS estoque_insumos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item TEXT UNIQUE, quantidade_kg REAL, unidade TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS estoque_admin (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT UNIQUE, categoria TEXT, quantidade INTEGER
)
""")

# Inicializar insumos padrões
insumos_iniciais = [
    ("Brita 0", 50000.0, "kg"),
    ("Brita 3/4", 50000.0, "kg"),
    ("Pó de Brita", 50000.0, "kg"),
    ("CAP", 20000.0, "kg"),
    ("Imprimante", 5000.0, "L"),
    ("Cola", 5000.0, "L")
]
for item, qtd, uni in insumos_iniciais:
    cursor.execute("INSERT OR IGNORE INTO estoque_insumos (item, quantidade_kg, unidade) VALUES (?, ?, ?)", (item, qtd, uni))

conn.commit()
os.makedirs("fotos_caminhoes", exist_ok=True)

# ==========================================
# FUNÇÕES DE SUPORTE
# ==========================================
def ler_peso_balanca_serial(porta="COM3", baudrate=9600):
    if not SERIAL_DISPONIVEL:
        return None
    try:
        ser = serial.Serial(porta, baudrate, timeout=1)
        linha = ser.readline().decode('utf-8').strip()
        ser.close()
        peso = float(''.join(c for c in linha if c.isdigit() or c == '.'))
        return peso
    except Exception:
        return None

TRACPO_CBUQ_PERCENTUAL = {
    "Brita 0": 0.45,
    "Brita 3/4": 0.25,
    "Pó de Brita": 0.24,
    "CAP": 0.05,
    "Imprimante": 0.005,
    "Cola": 0.005
}

def dar_baixa_traco_cbuq(peso_liquido_kg):
    for insumo, percentual in TRACPO_CBUQ_PERCENTUAL.items():
        qtd_consumida = peso_liquido_kg * percentual
        cursor.execute("UPDATE estoque_insumos SET quantidade_kg = quantidade_kg - ? WHERE item = ?", (qtd_consumida, insumo))
    conn.commit()

# ==========================================
# GERENCIAMENTO DE SESSÃO / AUTENTICAÇÃO
# ==========================================
st.set_page_config(page_title="Gestão Usina de Asfalto", layout="wide")

if "autenticado" not in st.session_state:
    st.session_state["autenticado"] = False
    st.session_state["usuario"] = ""
    st.session_state["nome"] = ""
    st.session_state["perfil"] = ""

# ------------------------------------------
# TELA DE LOGIN
# ------------------------------------------
if not st.session_state["autenticado"]:
    st.markdown("<h2 style='text-align: center;'>🏭 Usina de Asfalto - Acesso ao Sistema</h2>", unsafe_allow_html=True)
    
    col_l1, col_l2, col_l3 = st.columns([1, 1, 1])
    with col_l2:
        with st.form("form_login"):
            input_user = st.text_input("Usuário:").strip().lower()
            input_pass = st.text_input("Senha:", type="password")
            btn_login = st.form_submit_button("Entrar no Sistema", use_container_width=True, type="primary")
            
            if btn_login:
                cursor.execute("SELECT senha_hash, nome, perfil FROM usuarios WHERE usuario = ?", (input_user,))
                resultado = cursor.fetchone()
                
                if resultado and verificar_senha(input_pass, resultado[0]):
                    st.session_state["autenticado"] = True
                    st.session_state["usuario"] = input_user
                    st.session_state["nome"] = resultado[1]
                    st.session_state["perfil"] = resultado[2]
                    st.rerun()
                else:
                    st.error("Usuário ou senha incorretos!")
    st.stop()

# ==========================================
# CABEÇALHO DO APLICATIVO LOGADO
# ==========================================
col_h1, col_h2 = st.columns([3, 1])
col_h1.title("🏭 Sistema de Controle - Usina de Asfalto")
with col_h2:
    st.write(f"👤 **{st.session_state['nome']}**")
    st.caption(f"Perfil: **{st.session_state['perfil']}**")
    if st.button("Sair / Logout", type="secondary"):
        st.session_state["autenticado"] = False
        st.rerun()

# Definir abas com base no nível de permissão
abas_lista = ["🚛 Balança / Pesagem", "🪨 Estoque Insumos", "🛠️ Almoxarifado", "📊 Relatórios"]
if st.session_state["perfil"] == "Administrador":
    abas_lista.append("👤 Gestão de Usuários")

abas = st.tabs(abas_lista)

# ------------------------------------------
# ABA 1: BALANÇA E CAMINHÕES (Acesso: Todos)
# ------------------------------------------
with abas[0]:
    st.header("Entrada e Saída de Caminhões")
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.subheader("Dados da Carga")
        placa = st.text_input("Placa do Veículo:").upper()
        motorista = st.text_input("Nome do Motorista:")
        tipo_mov = st.selectbox("Operação:", ["Saída (Massa Asfáltica - CBUQ)", "Entrada (Insumo/Matéria-Prima)"])
        
        materiais_lista = ["Massa Asfáltica CBUQ", "Brita 0", "Brita 3/4", "Pó de Brita", "CAP", "Imprimante", "Cola"]
        material = st.selectbox("Material:", materiais_lista)

        st.markdown("---")
        st.subheader("⚖️ Pesagem")
        col_bal1, col_bal2 = st.columns(2)
        usar_automacao = col_bal1.checkbox("Leitura automática (RS232/USB)")
        porta_com = col_bal2.text_input("Porta COM:", "COM3")
        
        peso_bruto_auto = 0.0
        if usar_automacao:
            peso_capturado = ler_peso_balanca_serial(porta=porta_com)
            if peso_capturado is not None:
                st.success(f"Peso lido: {peso_capturado:.2f} kg")
                peso_bruto_auto = peso_capturado
            else:
                st.warning("Falha na leitura automática.")
        
        c1, c2 = st.columns(2)
        peso_bruto = c1.number_input("Peso Bruto (kg):", value=peso_bruto_auto if peso_bruto_auto > 0 else 0.0, min_value=0.0)
        tara = c2.number_input("Tara (kg):", min_value=0.0)
        peso_liquido = abs(peso_bruto - tara)
        st.info(f"**Peso Líquido:** {peso_liquido:.2f} kg ({peso_liquido/1000:.2f} Ton)")

    with col2:
        st.subheader("Foto e Confirmação")
        foto = st.camera_input("Tirar foto da carga/placa")
        foto_upload = st.file_uploader("Ou envie uma imagem:", type=["jpg", "png", "jpeg"])
        
        if st.button("Salvar Registro de Pesagem", type="primary", use_container_width=True):
            if placa and material:
                foto_path = None
                data_atual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                img_ref = foto if foto else foto_upload
                if img_ref:
                    foto_path = f"fotos_caminhoes/{placa}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                    image = Image.open(img_ref)
                    image.save(foto_path)

                cursor.execute("""
                    INSERT INTO balanca (placa, motorista, tipo_movimento, material, peso_bruto, tara, peso_liquido, data_hora, foto_path, operador)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (placa, motorista, tipo_mov, material, peso_bruto, tara, peso_liquido, data_atual, foto_path, st.session_state["usuario"]))
                
                if tipo_mov.startswith("Saída") and material == "Massa Asfáltica CBUQ" and peso_liquido > 0:
                    dar_baixa_traco_cbuq(peso_liquido)
                    st.toast("⚡ Baixa de insumos realizada por traço CBUQ!", icon="🧪")
                elif tipo_mov.startswith("Entrada") and material in TRACPO_CBUQ_PERCENTUAL and peso_liquido > 0:
                    cursor.execute("UPDATE estoque_insumos SET quantidade_kg = quantidade_kg + ? WHERE item = ?", (peso_liquido, material))
                    conn.commit()

                st.success("✅ Pesagem salva com sucesso!")
            else:
                st.error("Preencha a placa e o material!")

    st.divider()
    df_caminhoes = pd.read_sql_query("SELECT id, placa, motorista, tipo_movimento, material, peso_liquido, data_hora, operador FROM balanca ORDER BY id DESC LIMIT 10", conn)
    st.dataframe(df_caminhoes, use_container_width=True)

# ------------------------------------------
# ABA 2: ESTOQUE DE INSUMOS (Acesso: Todos)
# ------------------------------------------
with abas[1]:
    st.header("Níveis de Estocagem de Insumos")
    col_e1, col_e2 = st.columns([1, 1])
    
    with col_e1:
        st.subheader("Estoque Atual")
        df_insumos = pd.read_sql_query("SELECT item as 'Insumo', quantidade_kg / 1000.0 as 'Estoque (Toneladas)' FROM estoque_insumos", conn)
        st.dataframe(df_insumos, use_container_width=True)

    with col_e2:
        st.subheader("Composição do Traço (CBUQ)")
        df_traco = pd.DataFrame([{"Insumo": k, "Proporção (%)": f"{v*100:.1f}%"} for k, v in TRACPO_CBUQ_PERCENTUAL.items()])
        st.table(df_traco)

# ------------------------------------------
# ABA 3: ALMOXARIFADO (Permissões diferenciadas)
# ------------------------------------------
with abas[2]:
    st.header("Estoque Administrativo e Manutenção")
    col_a1, col_a2 = st.columns(2)
    
    with col_a1:
        if st.session_state["perfil"] == "Administrador":
            st.subheader("Cadastrar / Entrada de Item")
            nome_item = st.text_input("Nome do Item:")
            categoria = st.selectbox("Categoria:", ["Manutenção", "Administrativo"])
            qtd_item = st.number_input("Quantidade:", min_value=1, step=1)
            
            if st.button("Adicionar ao Almoxarifado"):
                cursor.execute("""
                    INSERT INTO estoque_admin (nome, categoria, quantidade) VALUES (?, ?, ?)
                    ON CONFLICT(nome) DO UPDATE SET quantidade = quantidade + ?
                """, (nome_item, categoria, qtd_item, qtd_item))
                conn.commit()
                st.success("Estoque atualizado!")
        else:
            st.info("ℹ️ Apenas Administradores podem cadastrar ou dar entrada de itens no almoxarifado.")

    with col_a2:
        st.subheader("Consulta de Itens")
        df_admin = pd.read_sql_query("SELECT id, nome as 'Item', categoria as 'Categoria', quantidade as 'Qtd' FROM estoque_admin", conn)
        st.dataframe(df_admin, use_container_width=True)

# ------------------------------------------
# ABA 4: RELATÓRIOS (Acesso: Todos)
# ------------------------------------------
with abas[3]:
    st.header("Relatórios e Exportação")
    col_r1, col_r2 = st.columns(2)
    data_inicio = col_r1.date_input("Data Inicial", datetime.now())
    data_fim = col_r2.date_input("Data Final", datetime.now())
        
    df_export = pd.read_sql_query("""
        SELECT id, placa, motorista, tipo_movimento, material, peso_bruto, tara, peso_liquido, data_hora, operador
        FROM balanca 
        WHERE date(data_hora) BETWEEN ? AND ?
        ORDER BY id DESC
    """, conn, params=(data_inicio.strftime("%Y-%m-%d"), data_fim.strftime("%Y-%m-%d")))
    
    st.dataframe(df_export, use_container_width=True)
    
    if not df_export.empty:
        buffer_excel = io.BytesIO()
        with pd.ExcelWriter(buffer_excel, engine='openpyxl') as writer:
            df_export.to_excel(writer, index=False, sheet_name="Pesagens")
        
        st.download_button(
            label="📥 Baixar Relatório em Excel (.xlsx)",
            data=buffer_excel.getvalue(),
            file_name=f"relatorio_usina_{data_inicio}_a_{data_fim}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary"
        )

# ------------------------------------------
# ABA 5: GESTÃO DE USUÁRIOS (Exclusivo Administrador)
# ------------------------------------------
if st.session_state["perfil"] == "Administrador":
    with abas[4]:
        st.header("👤 Gestão de Conta e Acessos")
        
        col_u1, col_u2 = st.columns(2)
        
        with col_u1:
            st.subheader("Cadastrar Novo Usuário")
            novo_user = st.text_input("Usuário (Login):").strip().lower()
            novo_nome = st.text_input("Nome Completo:")
            nova_senha = st.text_input("Senha:", type="password")
            novo_perfil = st.selectbox("Nível de Acesso:", ["Colaborador", "Administrador"])
            
            if st.button("Criar Usuário", type="primary"):
                if novo_user and nova_senha and novo_nome:
                    try:
                        cursor.execute("""
                            INSERT INTO usuarios (usuario, senha_hash, nome, perfil)
                            VALUES (?, ?, ?, ?)
                        """, (novo_user, gerhar_hash_senha(nova_senha), novo_nome, novo_perfil))
                        conn.commit()
                        st.success(f"Usuário **{novo_user}** criado com sucesso!")
                    except sqlite3.IntegrityError:
                        st.error("Este nome de usuário já existe.")
                else:
                    st.error("Preencha todos os campos!")

        with col_u2:
            st.subheader("Usuários Cadastrados")
            df_users = pd.read_sql_query("SELECT id, usuario as 'Login', nome as 'Nome', perfil as 'Perfil' FROM usuarios", conn)
            st.dataframe(df_users, use_container_width=True)
