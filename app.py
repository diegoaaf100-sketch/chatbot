import os
import time
import pandas as pd
import streamlit as st
import requests
from google import genai

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
# 1. LEITURA DA PLANILHA PRIVADA VIA EXPORTAÇÃO CSV
# =========================================================
@st.cache_data(ttl=600)
def carregar_aba(nome_aba: str) -> pd.DataFrame:
    """Carrega uma aba específica da planilha privada de forma segura usando o formato CSV do Google Sheets"""
    try:
        spreadsheet_url = st.secrets["connections"]["gsheets"]
        
        # Extrai o ID da planilha da URL
        if "/d/" in spreadsheet_url:
            sheet_id = spreadsheet_url.split("/d/")[1].split("/")[0]
        else:
            sheet_id = spreadsheet_url

        # Monta a URL de exportação da aba específica em formato CSV
        url_csv = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={requests.utils.quote(nome_aba)}"
        
        # Faz a requisição HTTP (suporta planilhas compartilhadas com contas de serviço se públicas, 
        # ou usa o formato de exportação direta do Google Sheets)
        df = pd.read_csv(url_csv, header=1) # header=1 indica que a linha 2 (index 1) é o cabeçalho
        
        # Limpeza do DataFrame
        df = df.dropna(how="all")
        # Remove colunas sem nome (vazias)
        df = df.loc[:, ~df.columns.str.contains('^Unnamed')]
        
        return df
    except Exception as e:
        st.error(f"Erro ao processar os dados da aba {nome_aba}: {e}")
        return pd.DataFrame()

# =========================================================
# 2. CONFIGURAÇÃO DO GEMINI (SDK MODERNO)
# =========================================================
api_key = st.secrets.get("GEMINI_API_KEY")
gemini_client = genai.Client(api_key=api_key) if api_key else None

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
    if not gemini_client:
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

    modelos_para_tentar = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
    ultimo_erro = ""

    for modelo in modelos_para_tentar:
        try:
            resposta = gemini_client.models.generate_content(
                model=modelo,
                contents=[prompt_sistema, f"Pergunta: {pergunta}"],
            )
            if resposta and resposta.text:
                return resposta.text
        except Exception as e:
            ultimo_erro = str(e)
            continue

    return f"Não foi possível consultar o Gemini. Detalhe: {ultimo_erro}"

# =========================================================
# 3. INTERFACE DO DASHBOARD NO STREAMLIT
# =========================================================
st.title("🛡️ Painel de Gestão e Relatórios de Efetivo")

st.sidebar.header("🗂️ Seleção de Unidade / Seção")
aba_selecionada = st.sidebar.selectbox("Selecione a OME / Unidade:", ABAS_VALIDAS)

df = carregar_aba(aba_selecionada)

if not df.empty:
    st.subheader(f"Efetivo da Unidade: {aba_selecionada}")
    
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

    st.sidebar.divider()
    st.sidebar.header("🔍 Filtros de Consulta")
    
    df_filtrado = df.copy()

    if "Posto / Graduação" in df.columns:
        postos = ["Todos"] + list(df["Posto / Graduação"].dropna().unique())
        filtro_posto = st.sidebar.selectbox("Filtrar por Posto / Graduação:", postos)
        if filtro_posto != "Todos":
            df_filtrado = df_filtrado[df_filtrado["Posto / Graduação"] == filtro_posto]

    if "Quadro" in df.columns:
        quadros = ["Todos"] + list(df["Quadro"].dropna().unique())
        filtro_quadro = st.sidebar.selectbox("Filtrar por Quadro:", quadros)
        if filtro_quadro != "Todos":
            df_filtrado = df_filtrado[df_filtrado["Quadro"] == filtro_quadro]

    st.markdown(f"### Registros ({len(df_filtrado)} encontrados)")
    st.dataframe(df_filtrado, use_container_width=True)

    csv = df_filtrado.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="📥 Baixar Relatório em CSV desta Unidade",
        data=csv,
        file_name=f"relatorio_efetivo_{aba_selecionada}.csv",
        mime='text/csv',
    )

    # =========================================================
    # 4. CHATBOT GEMINI INTEGRADO
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
        st.session_state.historico_chat.append({"role": "user", "content":pergunta})
        resposta = responder_chatbot(pergunta, df_filtrado)
        st.session_state.historico_chat.append({"role": "assistant", "content": resposta})
        st.rerun()

else:
    st.warning(f"Não foi possível carregar os dados da aba **{aba_selecionada}**. Verifique se a aba existe e se a planilha está configurada com permissão de visualização pública por link (ou compartilhada corretamente).")

st.divider()
st.caption("Painel de Efetivo • Desenvolvido com Streamlit e Google Sheets")
