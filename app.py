import streamlit as st
import pandas as pd
from datetime import datetime, date
import hashlib
import urllib.parse
from fpdf import FPDF
from supabase import create_client, Client
import cloudinary
import cloudinary.uploader

# ==========================================
# 1. CONFIGURAÇÕES, CONEXÕES E TRADUÇÃO CSS
# ==========================================
st.set_page_config(page_title="Usina Municipal de Vilhena", layout="wide", page_icon="🏭")

# Hack de CSS para traduzir os botões da câmera
st.markdown("""
    <style>
    /* Traduzir botão 'Take Photo' */
    [data-testid="stCameraInputButton"] {
        visibility: hidden;
        position: relative;
    }
    [data-testid="stCameraInputButton"]:after {
        content: '📸 Tirar Foto';
        visibility: visible;
        position: absolute;
        left: 50%;
        top: 50%;
        transform: translate(-50%, -50%);
        white-space: nowrap;
        background-color: #f0f2f6;
        padding: 10px;
        border-radius: 5px;
    }
    /* Traduzir botão 'Clear photo' para 'Próxima Foto' */
    [data-testid="stCameraInputClearButton"] {
        visibility: hidden;
        position: relative;
    }
    [data-testid="stCameraInputClearButton"]:after {
        content: '➕ Próxima Foto';
        visibility: visible;
        position: absolute;
        left: 50%;
        top: 50%;
        transform: translate(-50%, -50%);
        white-space: nowrap;
        background-color: #f0f2f6;
        padding: 10px;
        border-radius: 5px;
    }
    </style>
""", unsafe_allow_html=True)

try:
    url: str = st.secrets["SUPABASE_URL"]
    key_sup: str = st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(url, key_sup)
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
            # Formatação no PDF para o peso também usar ponto
            valor_str = f"{v:,.0f}".replace(",", ".") if k == "peso_liquido" else str(v)
            pdf.cell(60, 8, f"{str(k).upper().replace('_', ' ')}:", border=1)
            pdf.cell(130, 8, valor_str, border=1, ln=True)
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
    st.session_state.update({"autenticado": False, "usuario": "", "perfil": "", "fotos_temp": []})

if not st.session_state["autenticado"]:
    st.title("🏛️ Usina Municipal de Vilhena")
    with st.form("login"):
        u = st.text_input("Usuário").lower().strip()
        p = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            res = supabase.table("usuarios").select("*").eq("usuario", u).execute()
            if res.data and verificar_senha(p, res.data[0]['senha_hash']):
                st.session_state.update({"autenticado": True, "usuario": u, "nome": res.data[0]['nome'], "perfil": res.data[0]['perfil']})
                st.rerun()
            else: st.error("Acesso Negado.")
    st.stop()

# ==========================================
# 4. MENU E ABAS
# ==========================================
st.sidebar.title(f"👤 {st.session_state['nome']}")
if st.sidebar.button("Sair"):
    st.session_state.update({"autenticado": False, "fotos_temp": []})
    st.rerun()

perfis_acesso = {
    "Administrador": ["📊 Dashboard", "🚛 Balança", "🏗️ Traço CBUQ", "📦 Almoxarifado", "🛠️ Manutenção", "📈 Relatórios", "👥 Usuários"],
    "Operador Balança": ["📊 Dashboard", "🚛 Balança", "📈 Relatórios"],
    "Gestor Almoxarifado/Manutenção": ["📊 Dashboard", "📦 Almoxarifado", "🛠️ Manutenção", "📈 Relatórios"]
}

abas_disponiveis = perfis_acesso.get(st.session_state["perfil"], ["📊 Dashboard"])
tabs = st.tabs(abas_disponiveis)
tab_map = {nome: tabs[i] for i, nome in enumerate(abas_disponiveis)}

# --- TAB: DASHBOARD ---
if "📊 Dashboard" in tab_map:
    with tab_map["📊 Dashboard"]:
        st.header("Estoque de Insumos")
        res = supabase.table("estoque_insumos").select("*").execute()
        if res.data:
            df = pd.DataFrame(res.data)
            m = st.columns(len(df))
            # ALTERADO: ,.0f .replace(",", ".")
            for i, r in df.iterrows(): m[i].metric(r['item'], f"{r['quantidade_kg']:,.0f}".replace(",", ".") + " kg")
            st.bar_chart(df.set_index("item")["quantidade_kg"])

# --- TAB: BALANÇA ---
if "🚛 Balança" in tab_map:
    with tab_map["🚛 Balança"]:
        st.subheader("Registro de Pesagem")
        c1, c2 = st.columns(2)
        with c1:
            placa = st.text_input("Placa", key="placa_balanca").upper()
            motorista = st.text_input("Nome do Motorista", key="mot_balanca")
            tipo = st.selectbox("Operação", ["Saída (Massa Asfáltica)", "Entrada (Insumo)", "Saída (Diversos)"], key="tipo_balanca")
            if tipo == "Saída (Massa Asfáltica)": 
                material, destino = "Massa Asfáltica CBUQ", st.text_input("Destino/Obra", key="dest_balanca")
            elif tipo == "Entrada (Insumo)": 
                material, destino = st.selectbox("Insumo", ["CAP", "Pó de Brita", "Brita 0", "Brita 3/4", "Imprimante", "Cola"], key="ins_balanca"), "Usina"
            else: 
                material, destino = st.text_input("Material Diversos", key="mat_div_balanca"), st.text_input("Destino", key="dest_div_balanca")
            p_l = st.number_input("Peso Líquido (kg)", 0.0, key="peso_balanca")
        with c2:
            st.info("💡 Tire a foto e clique em 'Próxima Foto' para tirar mais uma.")
            foto_capturada = st.camera_input("Capturar Imagem", key="camera_balanca")
            
            if foto_capturada:
                if foto_capturada not in st.session_state["fotos_temp"]:
                    st.session_state["fotos_temp"].append(foto_capturada)
                    st.toast(f"✅ Foto {len(st.session_state['fotos_temp'])} capturada!")
            
            if st.session_state["fotos_temp"]:
                st.write(f"📸 Fotos prontas para salvar: **{len(st.session_state['fotos_temp'])}**")
                if st.button("🗑️ Limpar Todas as Fotos", key="btn_limpar_fotos"):
                    st.session_state["fotos_temp"] = []
                    st.rerun()

            if st.button("💾 Finalizar Registro e Salvar", key="btn_salvar_balanca"):
                if placa and motorista and p_l > 0:
                    with st.spinner("Enviando dados e fotos..."):
                        lista_urls = []
                        for f in st.session_state["fotos_temp"]:
                            try: lista_urls.append(cloudinary.uploader.upload(f)["secure_url"])
                            except: pass
                        foto_url_final = ",".join(lista_urls) if lista_urls else None
                        dados = {"placa": placa, "motorista": motorista, "tipo_movimento": tipo, "material": material, "peso_liquido": p_l, "destino": destino, "operador": st.session_state['usuario'], "foto_url": foto_url_final}
                        try:
                            supabase.table("balanca").insert(dados).execute()
                            if tipo == "Entrada (Insumo)": atualizar_estoque_direto(material, p_l, "soma")
                            elif tipo == "Saída (Massa Asfáltica)": dar_baixa_estoque_cbuq(p_l)
                            elif tipo == "Saída (Diversos)": atualizar_estoque_direto(material, p_l, "subtrai")
                            st.success("✅ Registro concluído com sucesso!"); st.session_state["fotos_temp"] = []
                            st.download_button("📥 Baixar Comprovante PDF", gerar_pdf_ticket(dados), f"ticket_{placa}.pdf", key="btn_pdf_balanca")
                        except Exception as e: st.error(f"Erro no banco: {e}")
                else: st.warning("Por favor, preencha Placa, Motorista e Peso antes de finalizar.")

# --- TAB: RELATÓRIOS ---
if "📈 Relatórios" in tab_map:
    with tab_map["📈 Relatórios"]:
        sub1, sub2 = st.tabs(["📲 Enviar WhatsApp", "🔍 Histórico e Fotos"])
        
        with sub1:
            st.header("Relatório de Movimentação")
            inicio_hoje = datetime.now().strftime('%Y-%m-%dT00:00:00')
            texto = f"🏛️ *USINA VILHENA* - {datetime.now().strftime('%d/%m/%Y')}\n\n"
            try:
                res_m = supabase.table("balanca").select("*").gte("created_at", inicio_hoje).execute()
                if res_m.data:
                    df_m = pd.DataFrame(res_m.data)
                    texto += "*🚀 MOVIMENTAÇÃO HOJE:*\n"
                    agrupado = df_m.groupby(['tipo_movimento', 'material'])['peso_liquido'].sum().reset_index()
                    for _, r in agrupado.iterrows():
                        # ALTERADO: ,.0f .replace(",", ".")
                        peso_f = f"{r['peso_liquido']:,.0f}".replace(",", ".")
                        texto += f"{'⬅️' if 'Entrada' in r['tipo_movimento'] else '➡️'} {r['material']}: {peso_f} kg\n"
                
                res_e = supabase.table("estoque_insumos").select("*").execute()
                if res_e.data:
                    texto += "\n*📦 ESTOQUE ATUAL:*\n"
                    for r in res_e.data: 
                        # ALTERADO: ,.0f .replace(",", ".")
                        estoque_f = f"{r['quantidade_kg']:,.0f}".replace(",", ".")
                        texto += f"• {r['item']}: {estoque_f} kg\n"
            except: pass
            st.markdown(f"[🟢 Enviar Relatório via WhatsApp](https://wa.me/?text={urllib.parse.quote(texto)})")

        with sub2:
            st.header("Consulta de Histórico")
            col_f1, col_f2 = st.columns(2)
            with col_f1: d_busca = st.date_input("Dia", date.today(), key="data_busca_rel")
            with col_f2: p_busca = st.text_input("Filtrar por Placa", key="placa_busca_rel").upper()
            
            res_h = supabase.table("balanca").select("*").gte("created_at", d_busca.isoformat()).lte("created_at", d_busca.isoformat() + "T23:59:59").execute()
            if res_h.data:
                df_h = pd.DataFrame(res_h.data)
                if p_busca: df_h = df_h[df_h['placa'].str.contains(p_busca)]
                
                for _, row in df_h.iterrows():
                    # ALTERADO: exibição no expander também com ponto
                    peso_h = f"{row['peso_liquido']:,.0f}".replace(",", ".")
                    with st.expander(f"🚛 {row['placa']} - {row['material']} ({peso_h}kg)"):
                        st.write(f"**Motorista:** {row['motorista']} | **Destino:** {row['destino']} | **Operador:** {row['operador']}")
                        
                        if row.get('foto_url') and str(row['foto_url']).strip() != "" and str(row['foto_url']) != "None":
                            links = str(row['foto_url']).split(",")
                            cols = st.columns(min(len(links), 4))
                            for idx, link in enumerate(links):
                                clean_link = str(link).strip()
                                if clean_link.startswith("http"):
                                    try:
                                        cols[idx % 4].image(clean_link, use_container_width=True)
                                    except:
                                        cols[idx % 4].warning("Imagem indisponível.")
                        else:
                            st.info("Nenhuma foto anexada a este registro.")

# --- TAB: ALMOXARIFADO ---
if "📦 Almoxarifado" in tab_map:
    with tab_map["📦 Almoxarifado"]:
        m_alm = st.radio("Menu:", ["Estoque", "Movimentar Material", "Cadastrar Novo Item"], horizontal=True, key="menu_alm_radio")
        res_alm = supabase.table("almoxarifado").select("*").execute()
        if m_alm == "Estoque" and res_alm.data:
            st.dataframe(pd.DataFrame(res_alm.data)[['item', 'categoria', 'quantidade', 'unidade']], use_container_width=True)
        elif m_alm == "Movimentar Material":
            itens = [r['item'] for r in res_alm.data] if res_alm.data else []
            if itens:
                with st.form("f_alm_mov"):
                    it, tm, qm = st.selectbox("Material", itens, key="sel_item_alm"), st.selectbox("Ação", ["Entrada", "Saída"], key="sel_tipo_alm"), st.number_input("Quantidade", 0.1, key="num_qtd_alm")
                    if st.form_submit_button("Confirmar Movimentação"):
                        cur = next(i['quantidade'] for i in res_alm.data if i['item'] == it)
                        supabase.table("almoxarifado").update({"quantidade": (cur+qm) if tm=="Entrada" else (cur-qm)}).eq("item", it).execute()
                        st.success("Estoque atualizado!"); st.rerun()
        elif m_alm == "Cadastrar Novo Item":
            with st.form("f_alm_cad"):
                ni, nc, nu = st.text_input("Nome do Item", key="ni_alm"), st.selectbox("Categoria", ["Escritório", "Manutenção", "Limpeza"], key="nc_alm"), st.text_input("Unidade de Medida", key="nu_alm")
                if st.form_submit_button("Salvar Item"):
                    supabase.table("almoxarifado").insert({"item": ni, "categoria": nc, "unidade": nu, "quantidade": 0}).execute()
                    st.success("Item cadastrado!"); st.rerun()

# --- TAB: TRAÇO CBUQ ---
if "🏗️ Traço CBUQ" in tab_map:
    with tab_map["🏗️ Traço CBUQ"]:
        res_t = supabase.table("config_traco").select("*").execute()
        if res_t.data:
            with st.form("f_traco_config"):
                n_p = {r['item']: st.number_input(f"% {r['item']}", 0.0, 100.0, float(r['porcentagem']), key=f"tr_{r['item']}") for r in res_t.data}
                if st.form_submit_button("Salvar Novo Traço"):
                    for k, v in n_p.items(): supabase.table("config_traco").update({"porcentagem": v}).eq("item", k).execute()
                    st.success("Traço de CBUQ atualizado!"); st.rerun()

# --- TAB: MANUTENÇÃO ---
if "🛠️ Manutenção" in tab_map:
    with tab_map["🛠️ Manutenção"]:
        st.subheader("Diário de Paradas e Manutenção")
        with st.form("f_manut_reg"):
            mot = st.selectbox("Motivo da Parada", ["Preventiva", "Quebra", "Chuva", "Falta de Insumo"], key="mot_manut")
            d1, h1 = st.date_input("Início da Parada", key="d1_manut"), st.time_input("Hora Início", key="h1_manut")
            d2, h2 = st.date_input("Retorno da Produção", key="d2_manut"), st.time_input("Hora Fim", key="h2_manut")
            if st.form_submit_button("Registrar Evento"):
                t = (datetime.combine(d2, h2) - datetime.combine(d1, h1)).total_seconds() / 3600
                if t > 0:
                    supabase.table("manutencao_paradas").insert({"motivo": mot, "tempo": round(t, 2), "data_inicio": datetime.combine(d1, h1).isoformat(), "data_fim": datetime.combine(d2, h2).isoformat()}).execute()
                    st.success(f"Registrado com sucesso: {t:.2f}h de parada."); st.rerun()
                else:
                    st.error("A data/hora de retorno deve ser posterior à de início.")

# --- TAB: USUÁRIOS ---
if "👥 Usuários" in tab_map:
    with tab_map["👥 Usuários"]:
        st.header("Gestão de Operadores e Acesso")
        res_u = supabase.table("usuarios").select("usuario, nome, perfil").execute()
        if res_u.data: st.table(pd.DataFrame(res_u.data))
        with st.form("f_u_cad"):
            nu, nn, np, ns = st.text_input("Login (Usuário)", key="u_login"), st.text_input("Nome Completo", key="u_nome"), st.selectbox("Perfil de Acesso", ["Operador Balança", "Gestor Almoxarifado/Manutenção", "Administrador"], key="u_perfil"), st.text_input("Senha de Acesso", type="password", key="u_senha")
            if st.form_submit_button("Criar Conta"):
                if nu and ns:
                    supabase.table("usuarios").insert({"usuario": nu.lower(), "senha_hash": gerar_hash_senha(ns), "nome": nn, "perfil": np}).execute()
                    st.success(f"Usuário {nu} criado com sucesso!"); st.rerun()
                else: st.warning("Preencha todos os campos obrigatórios.")