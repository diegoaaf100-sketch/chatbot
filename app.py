import os
import time
import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import google.generativeai as genai

# Configuração da página do Streamlit
st.set_page_config(page_title="Painel de Efetivo e Relatórios", page_icon="📊", layout="wide")

# =========================================================
# 1. CONEXÃO COM A PLANILHA PRIVADA (MÚLTIPLAS ABAS)
# =========================================================
@st.cache_resource
def conectar_google_sheets():
    """Autentica e conecta ao Google Sheets usando as credenciais do st.secrets"""
    scope = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly"
    ]
    
    # Pega as credenciais dos Secrets do Streamlit
    cred_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(cred_dict, scopes=scope)
    client = gspread.authorize(creds)
    
    # Abre a planilha pelo link configurado nos secrets
    spreadsheet_url = st.secrets["connections"]["gsheets"]
    return client.open_by_url(spreadsheet_url)

@st.cache_data(ttl=600)
def carregar_aba(nome_aba: str) -> pd.DataFrame:
    """Carrega uma aba específica da planilha como DataFrame do Pandas"""
    try:
        sh = conectar_google_sheets()
        worksheet = sh.worksheet(nome_aba)
        dados = worksheet.get_all_records()
        return pd.DataFrame(dados)
    except Exception as e:
        st.error(f"Erro ao carregar a aba '{nome_aba}': {e}")
        return pd.DataFrame()

# =========================================================
# 2. CONFIGURAÇÃO DO GEMINI
# =========================================================
api_key = st.secrets.get("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key)

def responder_chatbot(pergunta: str, dados: pd.DataFrame) -> str:
    if not api_key:
        return "A chave GEMINI_API_KEY não está configurada nos Secrets."

    # Resumo agregado para garantir privacidade e eficiência
    resumo = {
        "total_registros": len(dados),
        "colunas_disponiveis": list(dados.columns),
        "amostra_dados": dados.head(5).to_dict(orient="records")
    }

    prompt_sistema = f"""
Você é um assistente analítico integrado a um dashboard de relatórios.
Responda em português brasileiro de forma clara e objetiva.
Use exclusivamente os dados agregados e o contexto fornecidos abaixo. Não invente informações.
Não solicite nem revele dados pessoais sensíveis individuais.

Resumo dos dados da aba selecionada:
{resumo}
"""

    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        resposta = model.generate_content([prompt_sistema, f"Pergunta: {pergunta}"])
        return resposta.text or "O Gemini não retornou uma resposta textual."
    except Exception as e:
        return f"Erro ao consultar o Gemini: {e}"

# =========================================================
# 3. INTERFACE DO DASHBOARD
# =========================================================
st.title("📊 Painel de Relatórios e Gestão")

try:
    sh = conectar_google_sheets()
    # Lista o nome de todas as abas da planilha
    abas_disponiveis = [ws.title for ws in sh.worksheets()]
except Exception as e:
    st.error(f"Não foi possível conectar à planilha. Verifique as permissões e os Secrets. Detalhe: {e}")
    abas_disponiveis = []

if abas_disponiveis:
    # Menu lateral para selecionar a aba que deseja visualizar
    st.sidebar.header("🗂️ Navegação")
    aba_selecionada = st.sidebar.selectbox("Selecione a Aba da Planilha:", abas_disponiveis)

    # Carrega os dados da aba escolhida
    df = carregar_aba(aba_selecionada)

    if not df.empty:
        st.subheader(f"Visualizando Aba: {aba_selecionada}")
        
        # Filtros básicos na barra lateral
        st.sidebar.divider()
        st.sidebar.header("🔍 Filtros")
        
        # Exemplo de filtro dinâmico por coluna se houver dados
        colunas_filtro = [c for c in df.columns if df[c].dtype == 'object']
        df_filtrado = df.copy()
        
        if colunas_filtro:
            col_escolhida = st.sidebar.selectbox("Filtrar por coluna:", ["Nenhum"] + colunas_filtro)
            if col_escolhida != "Nenhum":
                valores_unicos = ["Todos"] + list(df[col_escolhida].unique())
                val_filtro = st.sidebar.selectbox(f"Selecione o valor para {col_escolhida}:", valores_unicos)
                if val_filtro != "Todos":
                    df_filtrado = df[df[col_escolhida] == val_filtro]

        # Exibição da tabela de dados filtrados
        st.dataframe(df_filtrado, use_container_width=True)
        st.caption(f"Total de registros exibidos: {len(df_filtrado)} de {len(df)}")

        # =====================================================
        # 4. CHATBOT GEMINI INTEGRADO
        # =====================================================
        st.divider()
        st.subheader("💬 Chatbot de Consulta com Gemini (Gratuito)")
        st.write("Faça perguntas sobre os dados da aba que está visualizando no momento.")

        if "historico_chat" not in st.session_state:
            st.session_state.historico_chat = []

        for mensagem in st.session_state.historico_chat:
            with st.chat_message(mensagem["role"]):
                st.markdown(mensagem["content"])

        pergunta = st.chat_input("Ex.: Faça um resumo dos dados desta aba...")

        if pergunta:
            st.session_state.historico_chat.append({"role": "user", "content": pergunta})
            resposta = responder_chatbot(pergunta, df_filtrado)
            st.session_state.historico_chat.append({"role": "assistant", "content": resposta})
            st.rerun()

    else:
        st.warning("A aba selecionada está vazia ou não pôde ser lida.")
else:
    st.info("Aguardando configuração correta da planilha e permissões para exibir as abas.")

# Rodapé
st.divider()
st.caption("Painel integrado com Google Sheets e Google Gemini • Uso Interno")
