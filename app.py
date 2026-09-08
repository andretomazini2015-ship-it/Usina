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
            for i, r in df.iterrows(): m[i].metric(r['item'], f"{r['quantidade_kg']:,.0f} kg")
            st.bar_chart(df.set_index("item")["quantidade_kg"])

# --- TAB: BALANÇA ---
if "🚛 Balança" in tab_map:
    with tab_map["🚛 Balança"]:
        st.subheader("Registro de Pesagem")
        c1, c2 = st.columns(2)
        with c1:
            placa = st.text_input("Placa").upper()
            motorista = st.text_input("Nome do Motorista")
            tipo = st.selectbox("Operação", ["Saída (Massa Asfáltica)", "Entrada (Insumo)", "Saída (Diversos)"])
            if tipo == "Saída (Massa Asfáltica)": material, destino = "Massa Asfáltica CBUQ", st.text_input("Destino/Obra")
            elif tipo == "Entrada (Insumo)": material, destino = st.selectbox("Insumo", ["CAP", "Pó de Brita", "Brita 0", "Brita 3/4", "Imprimante", "Cola"]), "Usina"
            else: material, destino = st.text_input("Material Diversos"), st.text_input("Destino")
            p_l = st.number_input("Peso Líquido (kg)", 0.0)
        with c2:
            st.write("**📷 Capturar Fotos**")
            foto_capturada = st.camera_input("Tirar Foto")
            if foto_capturada:
                if foto_capturada not in st.session_state["fotos_temp"]:
                    st.session_state["fotos_temp"].append(foto_capturada)
                    st.success(f"Foto {len(st.session_state['fotos_temp'])} adicionada!")
            if st.session_state["fotos_temp"]:
                st.write(f"Total de fotos prontas: {len(st.session_state['fotos_temp'])}")
                if st.button("🗑️ Limpar Fotos"):
                    st.session_state["fotos_temp"] = []
                    st.rerun()
            if st.button("💾 Finalizar Registro"):
                if placa and motorista and p_l > 0:
                    with st.spinner("Enviando fotos..."):
                        lista_urls = []
                        for f in st.session_state["fotos_temp"]:
                            try: lista_urls.append(cloudinary.uploader.upload(f)["secure_url"])
                            except: pass
                        dados = {"placa": placa, "motorista": motorista, "tipo_movimento": tipo, "material": material, "peso_liquido": p_l, "destino": destino, "operador": st.session_state['usuario'], "foto_url": ",".join(lista_urls)}
                        try:
                            supabase.table("balanca").insert(dados).execute()
                            if tipo == "Entrada (Insumo)": atualizar_estoque_direto(material, p_l, "soma")
                            elif tipo == "Saída (Massa Asfáltica)": dar_baixa_estoque_cbuq(p_l)
                            elif tipo == "Saída (Diversos)": atualizar_estoque_direto(material, p_l, "subtrai")
                            st.success("✅ Salvo!"); st.session_state["fotos_temp"] = []
                            st.download_button("📥 PDF", gerar_pdf_ticket(dados), f"ticket_{placa}.pdf")
                        except Exception as e: st.error(f"Erro: {e}")

# --- TAB: RELATÓRIOS (NOVA SUBSEÇÃO DE FOTOS) ---
if "📈 Relatórios" in tab_map:
    with tab_map["📈 Relatórios"]:
        sub_tab1, sub_tab2 = st.tabs(["WhatsApp", "🔍 Consulta de Pesagens/Fotos"])
        
        with sub_tab1:
            st.header("Relatório WhatsApp")
            inicio_hoje = datetime.now().strftime('%Y-%m-%dT00:00:00')
            texto = f"🏛️ *USINA VILHENA* - {datetime.now().strftime('%d/%m/%Y')}\n\n"
            res_m = supabase.table("balanca").select("*").gte("created_at", inicio_hoje).execute()
            if res_m.data:
                df_m = pd.DataFrame(res_m.data)
                texto += "*🚀 MOVIMENTAÇÃO HOJE:*\n"
                agrupado = df_m.groupby(['tipo_movimento', 'material'])['peso_liquido'].sum().reset_index()
                for _, r in agrupado.iterrows():
                    texto += f"{'⬅️' if 'Entrada' in r['tipo_movimento'] else '➡️'} {r['material']}: {r['peso_liquido']:,.0f} kg\n"
            link = f"https://wa.me/?text={urllib.parse.quote(texto)}"
            st.markdown(f"[🟢 Enviar WhatsApp]({link})")

        with sub_tab2:
            st.header("Consulta de Histórico")
            col_f1, col_f2 = st.columns(2)
            with col_f1:
                data_busca = st.date_input("Selecione o Dia", date.today())
            with col_f2:
                placa_busca = st.text_input("Filtrar por Placa (Opcional)").upper()
            
            query = supabase.table("balanca").select("*").gte("created_at", data_busca.isoformat()).lte("created_at", data_busca.isoformat() + "T23:59:59")
            if placa_busca:
                query = query.eq("placa", placa_busca)
            
            res_h = query.execute()
            if res_h.data:
                df_h = pd.DataFrame(res_h.data)
                st.write(f"Encontrados {len(df_h)} registros:")
                
                for _, row in df_h.iterrows():
                    with st.expander(f"🚛 {row['placa']} - {row['material']} - {row['peso_liquido']}kg"):
                        c_det1, c_det2 = st.columns(2)
                        with c_det1:
                            st.write(f"**Motorista:** {row['motorista']}")
                            st.write(f"**Operação:** {row['tipo_movimento']}")
                            st.write(f"**Destino:** {row['destino']}")
                            st.write(f"**Operador:** {row['operador']}")
                        with c_det2:
                            st.write("**Fotos do Carregamento:**")
                            if row['foto_url']:
                                links = row['foto_url'].split(",")
                                cols_fotos = st.columns(len(links))
                                for idx, link in enumerate(links):
                                    cols_fotos[idx].image(link, use_container_width=True)
                            else:
                                st.info("Nenhuma foto registrada para este veículo.")
            else:
                st.warning("Nenhum registro encontrado para este filtro.")

# --- TAB: ALMOXARIFADO ---
if "📦 Almoxarifado" in tab_map:
    with tab_map["📦 Almoxarifado"]:
        menu_alm = st.radio("Ação:", ["Estoque", "Movimentar", "Cadastrar"], horizontal=True)
        res_alm = supabase.table("almoxarifado").select("*").execute()
        if menu_alm == "Estoque" and res_alm.data:
            st.dataframe(pd.DataFrame(res_alm.data)[['item', 'categoria', 'quantidade', 'unidade']], use_container_width=True)
        elif menu_alm == "Movimentar":
            itens = [r['item'] for r in res_alm.data]
            with st.form("f_alm"):
                it, tm, qm = st.selectbox("Item", itens), st.selectbox("Tipo", ["Entrada", "Saída"]), st.number_input("Qtd", 0.1)
                if st.form_submit_button("Confirmar"):
                    cur = next(i['quantidade'] for i in res_alm.data if i['item'] == it)
                    supabase.table("almoxarifado").update({"quantidade": (cur+qm) if tm=="Entrada" else (cur-qm)}).eq("item", it).execute()
                    st.success("Atualizado!"); st.rerun()

# --- TAB: TRAÇO / MANUTENÇÃO / USUÁRIOS (Sincronizados) ---
if "🏗️ Traço CBUQ" in tab_map:
    with tab_map["🏗️ Traço CBUQ"]:
        res_t = supabase.table("config_traco").select("*").execute()
        with st.form("f_t"):
            n_p = {r['item']: st.number_input(f"% {r['item']}", 0.0, 100.0, float(r['porcentagem'])) for r in res_t.data}
            if st.form_submit_button("Salvar"):
                for k, v in n_p.items(): supabase.table("config_traco").update({"porcentagem": v}).eq("item", k).execute()
                st.rerun()

if "🛠️ Manutenção" in tab_map:
    with tab_map["🛠️ Manutenção"]:
        with st.form("f_m"):
            mot = st.selectbox("Motivo", ["Preventiva", "Quebra", "Chuva"])
            d1, h1 = st.date_input("Início"), st.time_input("Hora Início")
            d2, h2 = st.date_input("Fim"), st.time_input("Hora Fim")
            if st.form_submit_button("Registrar"):
                t = (datetime.combine(d2, h2) - datetime.combine(d1, h1)).total_seconds() / 3600
                supabase.table("manutencao_paradas").insert({"motivo": mot, "tempo": round(t, 2), "data_inicio": datetime.combine(d1, h1).isoformat(), "data_fim": datetime.combine(d2, h2).isoformat()}).execute()
                st.success(f"Registrado {t:.2f}h")

if "👥 Usuários" in tab_map:
    with tab_map["👥 Usuários"]:
        res_u = supabase.table("usuarios").select("usuario, nome, perfil").execute()
        st.table(pd.DataFrame(res_u.data))
        with st.form("f_u"):
            nu, nn, np, ns = st.text_input("Login"), st.text_input("Nome"), st.selectbox("Perfil", ["Operador Balança", "Gestor Almoxarifado/Manutenção", "Administrador"]), st.text_input("Senha", type="password")
            if st.form_submit_button("Criar"):
                supabase.table("usuarios").insert({"usuario": nu.lower(), "senha_hash": gerar_hash_senha(ns), "nome": nn, "perfil": np}).execute()
                st.rerun()