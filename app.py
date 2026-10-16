import os
import time
import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import google.generativeai as genai

# Configuração da página do Streamlit
st.set_page_config(page_title="Painel de Gestão de Efetivo", page_icon="🛡️", layout="wide")

# Lista exata das abas fornecidas
ABAS_VALIDAS = [
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
    """Autentica e conecta ao Google Sheets usando as credenciais do st.secrets"""
    scope = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly"
    ]
    cred_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(cred_dict, scopes=scope)
    client = gspread.authorize(creds)
    spreadsheet_url = st.secrets["connections"]["gsheets"]
    return client.open_by_url(spreadsheet_url)

@st.cache_data(ttl=600)
def carregar_aba(nome_aba: str) -> pd.DataFrame:
    """Carrega uma aba específica da planilha considerando que o cabeçalho está na linha 2"""
    try:
        sh = conectar_google_sheets()
        worksheets = sh.worksheets()
        ws_alvo = None
        
        # Procura a aba de forma flexível (ignorando variações de ° e º ou maiúsculas)
        for ws in worksheets:
            titulo_limpo = ws.title.strip().lower().replace("º", "°")
            alvo_limpo = nome_aba.strip().lower().replace("º", "°")
            if titulo_limpo == alvo_limpo:
                ws_alvo = ws
                break
                
        if ws_alvo:
            # Obtém todos os valores da aba como uma lista de listas
            todos_valores = ws_alvo.get_all_values()
            
            if len(todos_valores) < 2:
                return pd.DataFrame() # Aba vazia ou sem dados suficientes
                
            # A linha 2 (índice 1 no Python) é o cabeçalho
            cabecalho = [str(c).strip() for c in todos_valores[1]]
            
            # Da linha 3 em diante (índice 2 em diante) são os dados
            linhas_dados = todos_valores[2:]
            
            # Cria o DataFrame do Pandas limpo
            df = pd.DataFrame(linhas_dados, columns=cabecalho)
            
            # Remove linhas que estejam totalmente vazias
            df = df.dropna(how="all")
            
            # Remove colunas cujo nome seja vazio (caso existam colunas extras no final)
            df = df.loc[:, df.columns != ""]
            
            return df
        else:
            return pd.DataFrame()
    except Exception as e:
        st.error(f"Erro ao processar os dados da aba {nome_aba}: {e}")
        return pd.DataFrame()

# =========================================================
# 2. CONFIGURAÇÃO DO GEMINI
# =========================================================
api_key = st.secrets.get("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key)

def resumo_para_ia(df: pd.DataFrame) -> dict:
    """Gera um resumo estatístico e agregado dos dados para proteger a privacidade"""
    return {
        "total_efetivo": len(df),
        "postos_distribuicao": df["Posto / Graduação"].value_counts().head(10).to_dict() if "Posto / Graduação" in df.columns else {},
        "quadros_distribuicao": df["Quadro"].value_counts().to_dict() if "Quadro" in df.columns else {},
        "readaptados_total": int((df["Militar Readaptado"].astype(str).str.lower().isin(["sim", "s", "true", "1"])).sum()) if "Militar Readaptado" in df.columns else 0,
        "pcd_total": int((df["Militar PCD"].astype(str).str.lower().isin(["sim", "s", "true", "1"])).sum()) if "Militar PCD" in df.columns else 0,
    }

def responder_chatbot(pergunta: str, dados: pd.DataFrame) -> str:
    if not api_key:
        return "A chave GEMINI_API_KEY não está configurada nos Secrets."

    resumo = resumo_para_ia(dados)
    prompt_sistema = f"""
Você é um assistente analítico de efetivo militar integrado a um dashboard Streamlit.
Responda em português brasileiro de forma clara, estritamente objetiva e formal.
Use exclusivamente os indicadores agregados fornecidos abaixo. Não invente dados.
Nunca solicite nem tente inferir nomes, matrículas, e-mails, telefones ou detalhes pessoais individuais.

Resumo agregado da unidade/aba selecionada:
{resumo}
"""

    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        resposta = model.generate_content([prompt_sistema, f"Pergunta: {pergunta}"])
        return resposta.text or "O Gemini não retornou uma resposta textual."
    except Exception as e:
        return f"Erro ao consultar o Gemini: {e}"

# =========================================================
# 3. INTERFACE DO DASHBOARD NO STREAMLIT
# =========================================================
st.title("🛡️ Painel de Gestão e Relatórios de Efetivo")

st.sidebar.header("🗂️ Seleção de Unidade / Seção")
# Filtra apenas as abas válidas que existem na planilha do usuário
aba_selecionada = st.sidebar.selectbox("Selecione a OME / Unidade:", ABAS_VALIDAS)

# Carrega os dados da aba escolhida
df = carregar_aba(aba_selecionada)

if not df.empty:
    st.subheader(f"Efetivo da Unidade: {aba_selecionada}")
    
    # Métricas rápidas no topo
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total de Militares", len(df))
    with col2:
        readaptados = (df["Militar Readaptado"].astype(str).str.lower().isin(["sim", "s", "true", "1"])).sum() if "Militar Readaptado" in df.columns else 0
        st.metric("Readaptados", int(readaptados))
    with col3:
        pcd = (df["Militar PCD"].astype(str).str.lower().isin(["sim", "s", "true", "1"])).sum() if "Militar PCD" in df.columns else 0
        st.metric("PCD", int(pcd))
    with col4:
        punidos = df["Punição"].astype(str).str.strip().ne("").sum() if "Punição" in df.columns else 0
        st.metric("Com Punição Registrada", int(punidos))

    st.divider()

    # Filtros na barra lateral baseados nas colunas do cabeçalho
    st.sidebar.divider()
    st.sidebar.header("🔍 Filtros de Consulta")
    
    df_filtrado = df.copy()

    # Filtro por Posto / Graduação se a coluna existir
    if "Posto / Graduação" in df.columns:
        postos = ["Todos"] + list(df["Posto / Graduação"].dropna().unique())
        filtro_posto = st.sidebar.selectbox("Filtrar por Posto / Graduação:", postos)
        if filtro_posto != "Todos":
            df_filtrado = df_filtrado[df_filtrado["Posto / Graduação"] == filtro_posto]

    # Filtro por Quadro se a coluna existir
    if "Quadro" in df.columns:
        quadros = ["Todos"] + list(df["Quadro"].dropna().unique())
        filtro_quadro = st.sidebar.selectbox("Filtrar por Quadro:", quadros)
        if filtro_quadro != "Todos":
            df_filtrado = df_filtrado[df_filtrado["Quadro"] == filtro_quadro]

    # Exibição da tabela principal limpa e interativa
    st.markdown(f"### Registros ({len(df_filtrado)} encontrados)")
    st.dataframe(df_filtrado, use_container_width=True)

    # Botão para download dos dados filtrados em CSV para relatórios
    csv = df_filtrado.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="📥 Baixar Relatório em CSV desta Unidade",
        data=csv,
        file_name=f"relatorio_efetivo_{aba_selecionada}.csv",
        mime='text/csv',
    )

    # =========================================================
    # 4. CHATBOT GEMINI INTEGRADO (COM DADOS AGREGADOS)
    # =========================================================
    st.divider()
    st.subheader("💬 Chatbot de Consulta Inteligente (Gemini)")
    st.write(f"Faça perguntas sobre os totais e indicadores da unidade **{aba_selecionada}**.")

    if "historico_chat" not in st.session_state:
        st.session_state.historico_chat = []

    for mensagem in st.session_state.historico_chat:
        with st.chat_message(mensagem["role"]):
            st.markdown(mensagem["content"])

    pergunta = st.chat_input("Ex.: Quantos militares readaptados temos nesta unidade?")

    if pergunta:
        st.session_state.historico_chat.append({"role": "user", "content": pergunta})
        resposta = responder_chatbot(pergunta, df_filtrado)
        st.session_state.historico_chat.append({"role": "assistant", "content": resposta})
        st.rerun()

else:
    st.warning(f"Não foi possível carregar os dados da aba **{aba_selecionada}**. Verifique se a aba existe exatamente com esse nome na planilha privada e se a Conta de Serviço tem permissão de leitura.")

# Rodapé
st.divider()
st.caption("Painel de Efetivo • Desenvolvido com Streamlit e Google Sheets API")
