# 1. Melhore a função de PDF (Adicione .encode('latin-1', 'replace'))
def gerar_pdf_ticket(dados):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(190, 10, "PREFEITURA MUNICIPAL DE VILHENA", ln=True, align="C")
    pdf.ln(10)
    pdf.set_font("Arial", "", 12)
    
    for k, v in dados.items():
        # O .encode('latin-1', 'replace').decode('latin-1') evita erro de acentos
        texto_chave = f"{k.upper()}:".encode('latin-1', 'replace').decode('latin-1')
        texto_valor = f"{v}".encode('latin-1', 'replace').decode('latin-1')
        pdf.cell(50, 8, texto_chave, border=1)
        pdf.cell(140, 8, texto_valor, border=1, ln=True)
    
    # Retorna como bytes de forma segura
    return pdf.output() 

# 2. Na parte de Finalizar Registro (Tab 2), adicione o upload da foto:
with c2:
    foto = st.camera_input("Foto do Carregamento")
    if st.button("Finalizar Registro"):
        if p_l > 0 and placa:
            url_foto = ""
            if foto is not None:
                # Faz o upload real para o Cloudinary
                upload_result = cloudinary.uploader.upload(foto)
                url_foto = upload_result["secure_url"]

            dados = {
                "placa": placa, 
                "motorista": motorista, 
                "tipo_movimento": tipo_op, 
                "material": mat, 
                "peso_liquido": p_l, 
                "destino": destino, 
                "operador": st.session_state['usuario'],
                "foto_url": url_foto  # Salva o link da foto
            }
            
            try:
                supabase.table("balanca").insert(dados).execute()
                if "Saída" in tipo_op and mat == "Massa Asfáltica CBUQ": 
                    dar_baixa_estoque_cbuq(p_l)
                
                pdf_bytes = gerar_pdf_ticket(dados)
                st.download_button("📥 Baixar Ticket", data=pdf_bytes, file_name=f"ticket_{placa}.pdf", mime="application/pdf")
                st.success("✅ Registro salvo com sucesso!")
            except Exception as e:
                st.error(f"Erro ao salvar no banco: {e}")
        else:
            st.warning("Preencha a placa e os pesos.")