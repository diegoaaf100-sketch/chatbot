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

# =========================================================
# 1. CONEXÃO COM A PLANILHA PRIVADA E CARREGAMENTO DINÂMICO
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
    """Lê a matriz de dados com cabeçalho padronizado estritamente na Linha 2 (índice 1)."""
    if not matriz or len(matriz) < 2:
        return pd.DataFrame()
    
    # O cabeçalho fica padronizado na linha 2 da planilha (índice 1)
    idx_cabecalho = 1
    
    cabecalho_bruto = matriz[idx_cabecalho]
    
    # Remove colunas totalmente vazias do final do cabeçalho
    while cabecalho_bruto and not str(cabecalho_bruto[-1]).strip():
        cabecalho_bruto.pop()
        
    cabecalho = [str(c).strip() if str(c).strip() != "" else f"Coluna_{idx}" for idx, c in enumerate(cabecalho_bruto)]
    linhas = matriz[idx_cabecalho + 1:] # Linha 3 em diante
    
    dados_estruturados = []
    for linha in linhas:
        # Descarta linhas completamente vazias
        if not any(str(c).strip() for c in linha):
            continue
            
        item = {}
        for i, nome_col in enumerate(cabecalho):
            val = str(linha[i]).strip() if i < len(linha) and linha[i] is not None else ""
            item[nome_col] = val
        dados_estruturados.append(item)
        
    if not dados_estruturados:
        return pd.DataFrame()

    df = pd.DataFrame(dados_estruturados)
    df = df.dropna(how="all")
    
    # Normaliza nome da coluna Matrícula
    novos_nomes = {}
    for col in df.columns:
        col_lower = str(col).lower()
        if col_lower.startswith("matrícula") or col_lower.startswith("matricula"):
            novos_nomes[col] = "Matrícula"
    if novos_nomes:
        df = df.rename(columns=novos_nomes)
        
    df["Unidade_Origem"] = nome_aba
    return df

@st.cache_data(ttl=1800)
def carregar_todas_as_abas() -> dict:
    """Lê todas as abas existentes na planilha diretamente do Google Sheets."""
    try:
        sh = conectar_google_sheets()
        worksheets = sh.worksheets()
        
        abas_dict = {}
        for ws in worksheets:
            if ws.title.startswith("_"):
                continue
            matriz = ws.get_all_values()
            df_aba = processar_matriz_aba(matriz, ws.title)
            if not df_aba.empty:
                abas_dict[ws.title] = df_aba
                    
        return abas_dict
    except Exception as e:
        st.error(f"⚠️ Erro ao conectar e baixar dados do Google Sheets: {e}")
        return {}

todas_abas = carregar_todas_as_abas()
lista_abas_disponiveis = ["🔍 VISÃO GERAL"] + sorted(list(todas_abas.keys()))

st.sidebar.header("🗂️ Seleção de Unidade / Seção")
aba_selecionada = st.sidebar.selectbox("Selecione a OME / Unidade:", lista_abas_disponiveis, key="select_ome_unidade")

# =========================================================
# 2. MOTOR DE RELATÓRIOS DO CHATBOT
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
        
        colunas_desejadas = [col_posto, col_matricula, col_nome, col_ome, col_alvo, col_extra]
        
        cols_finais = []
        for c in colunas_desejadas:
            if c and c in df_temp.columns and c not in cols_finais:
                cols_finais.append(c)
                
        df_resumido = df_temp[cols_finais] if cols_finais else df_temp
        coluna_grafico = col_alvo if (col_alvo and col_alvo in df_resumido.columns) else col_posto
        
        aviso_coluna = ""
        if col_alvo and col_alvo in df_resumido.columns:
            aviso_coluna = f"\n📌 Coluna exibida no relatório: **{col_alvo}**"
        else:
            aviso_coluna = "\n⚠️ *Coluna não identificada na planilha. Exibindo colunas padrão.*"
        
        return {
            "texto": f"📋 **{titulo_relatorio}**{aviso_coluna}\n\nTotal de registros: **{len(df_temp)}**",
            "df": df_resumido,
            "coluna_grafico": coluna_grafico,
            "nome_arquivo": f"{titulo_relatorio.lower().replace(' ', '_')}.csv"
        }

    # 1. Matrícula
    if "matricula" in p:
        return gerar_resposta(col_matricula, "Relatório de Militares por Matrícula", por_numero=True)

    # 2. Nome de Guerra
    elif "nome de guerra" in p or "guerra" in p:
        col_guerra = buscar_coluna(df, ["nome de guerra", "guerra", "nome_guerra"])
        return gerar_resposta(col_guerra, "Relatório de Militares por Nome de Guerra")

    # 3. Nome / Ordem Alfabética
    elif "nome" in p or "alfabetica" in p or "alfabeto" in p:
        return gerar_resposta(col_nome, "Relatório de Militares por Ordem Alfabética")

    # 4. OME e Seção
    elif "secao" in p and "ome" in p:
        col_sec = buscar_coluna(df, ["secao", "seção", "subunidade", "divisao"])
        return gerar_resposta(col_ome, "Relatório de Militares por OME e Seção", col_extra=col_sec)

    # 5. OME
    elif "ome" in p or "unidade" in p:
        return gerar_resposta(col_ome, "Relatório de Militares por OME")

    # 6. Área de Formação 2
    elif "formacao 2" in p or "area de formacao 2" in p:
        col_f2 = buscar_coluna(df, ["area de formacao 2", "formacao 2", "area de formacao2"])
        return gerar_resposta(col_f2, "Relatório de Militares por Área de Formação 2")

    # 7. Área de Formação 1 (ou Área de Formação)
    elif "formacao" in p or "curso" in p or "graduacao" in p:
        col_f1 = buscar_coluna(df, ["area de formacao 1", "area de formacao", "formacao 1", "formacao"])
        return gerar_resposta(col_f1, "Relatório de Militares por Área de Formação")

    # 8. Escolaridade
    elif "escolaridade" in p or "instrucao" in p:
        col_esc = buscar_coluna(df, ["escolaridade", "instrucao", "grau", "nivel"])
        return gerar_resposta(col_esc, "Relatório de Militares por Escolaridade")

    # 9. Cidade
    elif "cidade" in p or "municipio" in p or "residencia" in p:
        col_cid = buscar_coluna(df, ["cidade", "municipio", "residencia", "endereco"])
        return gerar_resposta(col_cid, "Relatório de Militares por Cidade")

    # 10. Acumulação de Cargo
    elif "acumulacao" in p or "cargo" in
