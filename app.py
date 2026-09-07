import streamlit as st
import pandas as pd
from datetime import datetime
import hashlib
from supabase import create_client, Client
import cloudinary
import cloudinary.uploader
import urllib.parse

# ... (Configurações de conexões Supabase e Cloudinary permanecem as mesmas)

# ==========================================
# FUNÇÕES DE SEGURANÇA
# ==========================================
def gerar_hash_senha(senha):
    return hashlib.sha256(str.encode(senha)).hexdigest()

def verificar_senha(senha, hash_armazenado):
    return gerar_hash_senha(senha) == hash_armazenado

# ==========================================
# GESTÃO DO USUÁRIO MESTRE (ANDRE)
# ==========================================
def garantir_admin_padrao():
    user_admin = "andre"
    senha_admin = "02152518Ab@" # SENHA ATUALIZADA
    hash_novo = gerar_hash_senha(senha_admin)
    
    # Verifica se já existe
    res = supabase.table("usuarios").select("*").eq("usuario", user_admin).execute()
    
    if not res.data:
        # Cria se não existir
        novo_admin = {
            "usuario": user_admin,
            "senha_hash": hash_novo,
            "nome": "André (Administrador)",
            "perfil": "Administrador"
        }
        supabase.table("usuarios").insert(novo_admin).execute()
    else:
        # Força a atualização da senha caso tenha mudado no código
        supabase.table("usuarios").update({"senha_hash": hash_novo}).eq("usuario", user_admin).execute()

# Chamar a função
garantir_admin_padrao()

# ==========================================
# LÓGICA DO TRAÇO DE CBUQ (CORRIGIDA)
# ==========================================
def dar_baixa_estoque_cbuq(peso_liquido):
    TRACO = {
        "CAP": 0.05,            # 5%
        "Pó de Brita": 0.54,    # 54%
        "Brita 0": 0.23,        # 23%
        "Brita 3/4": 0.18       # 18%
    }
    for insumo, percentual in TRACO.items():
        qtd_consumida = peso_liquido * percentual
        res = supabase.table("estoque_insumos").select("quantidade_kg").eq("item", insumo).execute()
        if res.data:
            nova_qtd = res.data[0]['quantidade_kg'] - qtd_consumida
            supabase.table("estoque_insumos").update({"quantidade_kg": nova_qtd}).eq("item", insumo).execute()

# ==========================================
# INTERFACE E RELATÓRIO WHATSAPP
# ==========================================
# (O restante do código de Login, Balança e Relatório WhatsApp segue conforme configurado anteriormente)