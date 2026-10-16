import time
import json
import requests
import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

# Configuração da página do Streamlit
st.set_page_config(page_title="Painel de Gestão de Efetivo", page_icon="🛡️", layout="wide")

# =========================================================
# 0. SISTEMA DE AUTENTICAÇÃO (LOGIN E SENHA)
# =========================================================
def verificar_senha():
    """Retorna True se o usuário inseriu a senha correta."""
    
    def senha_inserida():
        usuario = st.session_state["username"]
        senha = st.session_state["password"]
        
        senhas_cadastradas = st.secrets.get("passwords", {})
        
        if usuario in senhas_cadastradas and senhas_cadastradas[usuario] == senha:
            st.session_state["senha_correta"] = True
            st.session_state["usuario_logado"] = usuario
            del st.session_state["password"]
        else:
            st.session_state["senha_correta"] = False

    if st.session_state.get("senha_correta", False):
        return True

    st.sidebar.markdown("### 🔐 Acesso Restrito")
    st.sidebar.text_input("Usuário", key="username")
    st.sidebar.text_input("Senha", type="password", key="password")
    st.sidebar.button("Entrar", on_click=senha_inserida)

    if "senha_correta" in st.session_state and not st.session_state["senha_correta"]:
        st.sidebar.error("😕 Usuário ou senha incorretos")
    
    return False

if not verificar_senha():
    st.info("👈 Por favor, insira seu usuário e senha na barra lateral para acessar o painel.")
    st.stop()

# =========================================================
# BOTÃO DE LOGOUT
# =========================================================
st.sidebar.divider()
st.sidebar.write(f"👤 Logado como: **{st.session_state.get('usuario_logado')}**")
if st.sidebar.button("🚪 Sair / Logout"):
    st.session_state["senha_correta"] = False
    st.session_state["usuario_logado"] = None
    st.rerun()

st.sidebar.divider()

# Lista exata das abas fornecidas + a Visão Geral
ABAS_VALIDAS = [
    "🔍 VISÃO GERAL",
    "1°GB", "2°GB", "3°GB", "4°GB", "5°GB", "6°GB", "7°GB", "9°GB", 
    "AGBM", "AECI", "AJG", "CAT AGRESTE", "CAT SERTÃO", "CAT ZONA DA MATA",
    "CAT/RMR", "CCS", "CEAO", "CEFD", "CI", "CINT", "CMAN", "CPO/CPP", 
    "CPPA", "DAS", "DEIP", "DF", "DGO", "DGP", "ADIDO", "DIESP", "DIM", 
    "DINTER/1", "DINTER/2", "DJD", "DLOG", "DPLAG", "DTIC", "DVP", 
    "GBAPH", "GBI", "GBMAR", "GBS", "GCG", "GSG"
]

# =========================================================
# 1. CONEXÃO COM A PLANILHA PRIVADA
# =========================================================
@st.cache_resource
def conectar_google_sheets():
    scope = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly"
    ]
    cred_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(cred_dict, scopes=scope)
    client = gspread.authorize(creds)
    
    raw_secret = st.secrets["connections"]["gsheets"]
    if isinstance(raw_secret, dict):
        spreadsheet_url = raw_secret.get("spreadsheet", "")
    else:
        spreadsheet_url = str(raw_secret)
        
    spreadsheet_url = spreadsheet_url.strip(" {}'\"")
    return client.open_by_url(spreadsheet_url)

@st.cache_data(ttl=600)
def carregar_aba(nome_aba: str) -> pd.DataFrame:
    try:
        sh = conectar_google_sheets()
        worksheets = sh.worksheets()
        ws_alvo = None
        
        import unicodedata
        def normalizar(texto):
            return ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn').strip().lower().replace("º", "°")
        
        alvo_normalizado = normalizar(nome_aba)
        
        for ws in worksheets:
            if normalizar(ws.title) == alvo_normalizado:
                ws_alvo = ws
                break
                
        if ws_alvo:
            matriz = ws_alvo.get_all_values()
            if len(matriz) < 2:
                return pd.DataFrame()
                
            cabecalho = [str(c).strip() for c in matriz[1]]
            linhas = matriz[2:]
            
            dados_estruturados = []
            for linha in linhas:
                while len(linha) < len(cabecalho):
                    linha.append("")
                item = {cabecalho[i]: str(linha[i]) if i < len(linha) and linha[i] is not None else "" for i in range(len(cabecalho))}
                dados_estruturados.append(item)
                
            df = pd.DataFrame(dados_estruturados)
            df = df.dropna(how="all")
            if "" in df.columns:
                df = df.drop(columns=[""])
                
            novos_nomes = {}
            for col in df.columns:
                if col.lower().startswith("matrícula") or col.lower().startswith("matricula"):
                    novos_nomes[col] = "Matrícula"
            if novos_nomes:
                df = df.rename(columns=novos_nomes)
                
            return df
        else:
            return pd.DataFrame()
    except Exception as e:
        return pd.DataFrame()

# =========================================================
# 2. CONFIGURAÇÃO DO GEMINI
# =========================================================
api_key = st.secrets.get("GEMINI_API_KEY", "")

def resumo_para_ia(df: pd.DataFrame) -> dict:
    return {
        "total_efetivo": len(df),
        "postos_distribuicao": df["Posto / Graduação"].value_counts().head(10).to_dict() if "Posto / Graduação" in df.columns else {},
        "quadros_distribuicao": df["Quadro"].value_counts().to_dict() if "Quadro" in df.columns else {},
        "readaptados_total": int((df["Militar Readaptado"].astype(str).str.lower().isin(["sim", "s", "true", "1"])).sum()) if "Militar Readaptado" in df.columns else 0,
        "pcd_total": int((df["Militar PCD"].astype(str).str.lower().isin(["sim", "s", "true", "1"])).sum()) if "Militar PCD" in df.columns else 0,
    }

def responder_chatbot(pergunta: str, dados: pd.DataFrame) -> str:
    if not api_key:
        return "⚠️ A chave GEMINI_API_KEY não está configurada nos Secrets
