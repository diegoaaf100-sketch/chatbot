import unicodedata
import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import time

# Configuração da página do Streamlit
st.set_page_config(page_title="Painel de Gestão de Efetivo", page_icon="🛡️", layout="wide")

# =========================================================
# 0. SISTEMA DE AUTENTICAÇÃO (LOGIN E SENHA) SEGURO
# =========================================================
def verificar_senha():
    """Retorna True se o usuário inseriu a senha correta."""
    
    def senha_inserida():
        usuario = st.session_state.get("username_input", "")
        senha = st.session_state.get("password_input", "")
        
        senhas_cadastradas = st.secrets.get("passwords", {})
        
        if usuario in senhas_cadastradas and senhas_cadastradas[usuario] == senha:
            st.session_state["senha_correta"] = True
            st.session_state["usuario_logado"] = usuario
            if "password_input" in st.session_state:
                del st.session_state["password_input"]
        else:
            st.session_state["senha_correta"] = False

    if st.session_state.get("senha_correta", False):
        return True

    st.sidebar.markdown("### 🔐 Acesso Restrito")
    st.sidebar.text_input("Usuário", key="username_input")
    st.sidebar.text_input("Senha", type="password", key="password_input")
    st.sidebar.button("Entrar", on_click=senha_inserida, key="btn_login")

    if st.session_state.get("senha_correta") is False:
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
if st.sidebar.button("🚪 Sair / Logout", key="btn_logout"):
    st.session_state["senha_correta"] = False
    st.session_state["usuario_logado"] = None
    st.rerun()

st.sidebar.divider()

# Lista exata das abas fornecidas + a Visão Geral
ABAS_VALIDAS = [
    "🔍 VISÃO GERAL",
    "1°GB", "2°GB", "3°GB", "4°GB", "5°GB", "6°GB", "7°GB", "9°GB", 
    "ABMG", "AECI", "AJG", "CAT AGRESTE", "CAT SERTÃO", "CAT ZONA DA MATA",
    "CAT/RMR", "CCS", "CEAO", "CEFD", "CI", "CINT", "CMAN", "CPO/CPP", 
    "CPPA", "DAS", "DEIP", "DF", "DGO", "DGP", "ADIDO", "DIESP", "DIM", 
    "DINTER/1", "DINTER/2", "DJD", "DLOG", "DPLAG", "DTIC", "DVP", 
    "GBAPH", "GBI", "GBMAR", "GBS", "GCG", "GSG"
]

# =========================================================
# 1. CONEXÃO COM A PLANILHA PRIVADA E CARREGAMENTO OTIMIZADO
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

def processar_matriz_aba(matriz, nome_aba):
    """Transforma a matriz bruta de valores da aba em DataFrame."""
    if not matriz or len(matriz) < 1:
        return pd.DataFrame()
    
    idx_cabecalho = 1 if len(matriz) > 1 and any(matriz[1]) else 0
    cabecalho = [str(c).strip() for c in matriz[idx_cabecalho]]
    linhas = matriz[idx_cabecalho + 1:]
    
    dados_estruturados = []
    for linha in linhas:
        if not any(linha):
            continue
        while len(linha) < len(cabecalho):
            linha.append("")
        item = {cabecalho[i]: str(linha[i]).strip() if i < len(linha) and linha[i] is not None else "" for i in range(len(cabecalho))}
        dados_estruturados.append(item)
        
    if not dados_estruturados:
        return pd.DataFrame()

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
        
    df["Unidade_Origem"] = nome_aba
    return df

@st.cache_data(ttl=1800)
def carregar_todas_as_abas() -> dict:
    """Lê todas as abas em lote reduzindo chamadas da API ao mínimo."""
    try:
        sh = conectar_google_sheets()
        worksheets = sh.worksheets()
        
        def normalizar(texto):
            return ''.join(c for c in unicodedata.normalize('NFD', str(texto)) if unicodedata.category(c) != 'Mn').strip().lower().replace("º", "°")
        
        abas_dict = {}
        for ws in worksheets:
            title_norm = normalizar(ws.title)
            # Verifica se a aba atual está na nossa lista de abas válidas
            for aba_valida in ABAS_VALIDAS:
                if aba_valida != "🔍 VISÃO GERAL" and normalizar(aba_valida) == title_norm:
                    matriz = ws.get_all_values()
                    df_aba = processar_matriz_aba(matriz, ws.title)
                    if not df_aba.empty:
                        abas_dict[aba_valida] = df_aba
                    break
                    
        return abas_dict
    except Exception as e:
        st.error(f"Erro ao conectar e baixar dados do Google Sheets: {e}")
        return {}

@st.cache_data(ttl=1800)
def carregar_aba(nome_aba: str) -> pd.DataFrame:
    dados_totais = carregar_todas_as_abas()
    return dados_totais.get(nome_aba, pd.DataFrame())

# =========================================================
# 2. MOTOR DE RELATÓRIOS DO CHATBOT (COM TRATAMENTO DE EM BRANCO)
# =========================================================
def buscar_coluna_exata(df: pd.DataFrame, termo_alvo: str) -> str:
    termo_norm = ''.join(c for c in unicodedata.normalize('NFD', termo_alvo) if unicodedata.category(c) != 'Mn').strip().lower()
    for col in df.columns:
        col_norm = ''.join(c for c in unicodedata.normalize('NFD', str(col)) if unicodedata.category(c) != 'Mn').strip().lower()
        if col_norm == termo_norm:
            return col
    for col in df.columns:
        col_norm = ''.join(c for c in unicodedata.normalize('NFD', str(col)) if unicodedata.category(c) != 'Mn').strip().lower()
        if termo_norm in col_norm:
            return col
    return None

def buscar_coluna(df: pd.DataFrame, termos_busca: list) -> str:
    for termo in termos_busca:
        res = buscar_coluna_exata(df, termo)
        if res:
            return res
    return None

def processar_relatorio_chat(pergunta: str, df: pd.DataFrame) -> dict:
    p = ''.join(c for c in unicodedata.normalize('NFD', pergunta) if unicodedata.category(c) != 'Mn').lower().strip()
    
    if df.empty:
        return {"texto": "⚠️ Não há dados disponíveis para gerar o relatório solicitado no momento."}

    col_posto = buscar_coluna(df, ["posto / graduacao", "posto/graduacao", "posto", "graduacao"])
    col_matricula = buscar_coluna(df, ["matricula", "matrícula", "mat"])
    col_nome = buscar_coluna(df, ["nome", "militar", "nome completo"])
    col_ome = buscar_coluna(df, ["ome", "unidade_origem", "unidade", "lotacao", "lotação"])

    def gerar_resposta(col_alvo, titulo_relatorio, por_numero=False, col_extra=None):
        df_temp = df.copy()
        
        cols_para_tratar = [c for c in [col_posto, col_matricula, col_nome, col_ome, col_alvo, col_extra] if c and c in df_temp.columns]
        for c in cols_para_tratar:
            df_temp[c] = df_temp[c].astype(str).str.strip().replace(["", "nan", "None", "null"], "Falta preencher")
        
        if col_alvo and col_alvo in df_temp.columns:
            if por_numero:
                df_temp["_sort_key"] = pd.to_numeric(df_temp[col_alvo].astype(str).str.extract(r'(\d+)')[0], errors='coerce').fillna(0)
                df_temp = df_temp.sort_values(by="_sort_key", ascending=True).drop(columns=["_sort_key"])
            else:
                df_temp = df_temp.sort_values(by=col_alvo, key=lambda x: x.astype(str).str.lower(), ascending=True)
        
        colunas_des
