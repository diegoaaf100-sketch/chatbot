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
        usuario = st.session_state.get("username", "")
        senha = st.session_state.get("password", "")
        
        senhas_cadastradas = st.secrets.get("passwords", {})
        
        if usuario in senhas_cadastradas and senhas_cadastradas[usuario] == senha:
            st.session_state["senha_correta"] = True
            st.session_state["usuario_logado"] = usuario
            if "password" in st.session_state:
                del st.session_state["password"]
        else:
            st.session_state["senha_correta"] = False

    if st.session_state.get("senha_correta", False):
        return True

    st.sidebar.markdown("### 🔐 Acesso Restrito")
    st.sidebar.text_input("Usuário", key="username")
    st.sidebar.text_input("Senha", type="password", key="password")
    st.sidebar.button("Entrar", on_click=senha_inserida)

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
# 2. MOTOR DE RELATÓRIOS DO CHATBOT (COLUNAS OBRIGATÓRIAS)
# =========================================================
def buscar_coluna(df: pd.DataFrame, termos_busca: list) -> str:
    for col in df.columns:
        col_norm = ''.join(c for c in unicodedata.normalize('NFD', col) if unicodedata.category(c) != 'Mn').strip().lower()
        for termo in termos_busca:
            if termo in col_norm:
                return col
    return None

def processar_relatorio_chat(pergunta: str, df: pd.DataFrame) -> dict:
    p = ''.join(c for c in unicodedata.normalize('NFD', pergunta) if unicodedata.category(c) != 'Mn').lower().strip()
    
    if df.empty:
        return {"texto": "⚠️ Não há dados disponíveis para gerar o relatório solicitado no momento."}

    col_posto = buscar_coluna(df, ["posto", "graduacao", "posto / graduacao"])
    col_matricula = buscar_coluna(df, ["matricula"])
    col_nome = buscar_coluna(df, ["nome", "militar", "nome completo"])
    col_ome = buscar_coluna(df, ["ome", "unidade", "unidade_origem"])

    def gerar_resposta(col_alvo, titulo_relatorio, por_numero=False, col_extra=None):
        df_temp = df.copy()
        
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
        
        return {
            "texto": f"📋 **{titulo_relatorio}**\n\nTotal de registros ordenados: **{len(df_temp)}**",
            "df": df_resumido,
            "nome_arquivo": f"{titulo_relatorio.lower().replace(' ', '_')}.csv"
        }

    if "matricula" in p:
        return gerar_resposta(col_matricula, "Relatório de Militares por Matrícula (Ordem Numérica)", por_numero=True)
    elif "nome de guerra" in p or "guerra" in p:
        col_guerra = buscar_coluna(df, ["guerra", "nome de guerra"])
        return gerar_resposta(col_guerra, "Relatório de Militares por Nome de Guerra")
    elif "nome" in p or "alfabetica" in p or "alfabeto" in p:
        return gerar_resposta(col_nome, "Relatório de Militares por Ordem Alfabética")
    elif "secao" in p and "ome" in p:
        col_sec = buscar_coluna(df, ["secao", "seção", "subunidade"])
        return gerar_resposta(col_ome, "Relatório de Militares por OME e Seção", col_extra=col_sec)
    elif "ome" in p or "unidade" in p:
        return gerar_resposta(col_ome, "Relatório de Militares por OME")
    elif "formacao 2" in p or "area de formacao 2" in p:
        col_f2 = buscar_coluna(df, ["formacao 2", "area de formacao 2", "formacao2"])
        return gerar_resposta(col_f2, "Relatório de Militares por Área de Formação 2")
    elif "formacao" in p or "curso" in p:
        col_f1 = buscar_coluna(df, ["formacao", "area de formacao", "graduacao"])
        return gerar_resposta(col_f1, "Relatório de Militares por Área de Formação")
    elif "escolaridade" in p or "instrucao" in p:
        col_esc = buscar_coluna(df, ["escolaridade", "instrucao", "grau"])
        return gerar_resposta(col_esc, "Relatório de Militares por Escolaridade")
    elif "cidade" in p or "municipio" in p or "residencia" in p:
        col_cid = buscar_coluna(df, ["cidade", "municipio", "residencia"])
        return gerar_resposta(col_cid, "Relatório de Militares por Cidade")
    elif "acumulacao" in p or "cargo" in p:
        col_ac = buscar_coluna(df, ["acumulacao", "cargo", "acumula"])
        return gerar_resposta(col_ac, "Relatório de Militares por Acumulação de Cargo Público")
    elif "afastamento" in p or "licenca" in p:
        col_af = buscar_coluna(df, ["afastamento", "status"])
        col_tipo = buscar_coluna(df, ["tipo de afastamento", "motivo", "tipo"])
        return gerar_resposta(col_af, "Relatório de Militares por Afastamento e Tipo de Afastamento", col_extra=col_tipo)
    else:
        return {
            "texto": (
                "🤖 **Menu de Relatórios Automatizados:**\n\n"
                "Digite uma das opções abaixo para gerar o relatório desejado:\n"
                "• Relatório de militares por ordem alfabética\n"
                "• Relatório de militares por OME\n"
                "• Relatório de militares por OME e seção\n"
                "• Relatório de militares por matrícula em ordem numérica\n"
                "• Relatório de militares por nome em ordem alfabética\n"
                "• Relatório de militares por nome de guerra em ordem alfabética\n"
                "• Relatório de militares por escolaridade\n"
                "• Relatório de militares por área de formação\n"
                "• Relatório de militares por área de formação 2\n"
                "• Relatório de militares por cidade\n"
                "• Relatório de militares por acumulação de cargo público\n"
                "• Relatório de militares por afastamento e tipo de afastamento"
            )
        }

# =========================================================
# 3. INTERFACE DO DASHBOARD NO STREAMLIT
# =========================================================

st.markdown("""
    <style>
    [data-testid="stImage"] img {
        border-radius: 50%;
    }
    </style>
""", unsafe_allow_html=True)

col_esq, col_img1, col_img2, col_dir = st.columns([2.5, 1, 1, 2.5])

with col_img1:
    st.image("brasao_cbmpe.png", use_container_width=True)

with col_img2:
    st.image("brasao_dgp.png", use_container_width=True)

st.markdown("<h1 style='text-align: center;'>Relatório do Efetivo</h1>", unsafe_allow_html=True)
st.divider()

st.sidebar.header("🗂️ Seleção de Unidade / Seção")
aba_selecionada = st.sidebar.selectbox("Selecione a OME / Unidade:", ABAS_VALIDAS)

if aba_selecionada == "🔍 VISÃO GERAL":
    lista_dfs = []
    with st.spinner("Consolidando dados de todas as unidades..."):
        for aba in ABAS_VALIDAS:
            if aba != "🔍 VISÃO GERAL":
                df_temp = carregar_aba(aba)
                if not df_temp.empty:
                    df_temp["Unidade_Origem"] = aba
                    lista_dfs.append(df_temp)
    if lista_dfs:
        df = pd.concat(lista_dfs, ignore_index=True)
    else:
        df = pd.DataFrame()
else:
    df = carregar_aba(aba_selecionada)

if not df.empty:
    st.sidebar.divider()
    st.sidebar.header("🔍 Filtros por Coluna")
    
    df_filtrado = df.copy()

    for coluna in df.columns:
        valores_unicos = df[coluna].dropna().unique()
        
        if len(valores_unicos) <= 25 and len(valores_unicos) > 1:
            opcoes = sorted([str(v) for v in valores_unicos if str(v).strip() != ""])
            if opcoes:
                selecao = st.sidebar.multiselect(f"Filtrar {coluna}:", options=opcoes)
                if selecao:
                    df_filtrado = df_filtrado[df_filtrado[coluna].astype(str).isin(selecao)]
        else:
            busca = st.sidebar.text_input(f"Buscar em {coluna}:")
            if busca:
                df_filtrado = df_filtrado[df_filtrado[coluna].astype(str).str.lower().str.contains(busca.lower(), na=False)]

    st.subheader(f"Efetivo: {aba_selecionada}")
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total de Militares", len(df_filtrado))
    with col2:
        readaptados = (df_filtrado["Militar Readaptado"].astype(str).str.lower().isin(["sim", "s", "true", "1"])).sum() if "Militar Readaptado" in df_filtrado.columns else 0
        st.metric("Readaptados", int(readaptados))
    with col3:
        pcd = (df_filtrado["Militar PCD"].astype(str).str.lower().isin(["sim", "s", "true", "1"])).sum() if "Militar PCD" in df_filtrado.columns else 0
        st.metric("PCD", int(pcd))
    with col4:
        punidos = df_filtrado["Punição"].astype(str).str.strip().ne("").sum() if "Punição" in df_filtrado.columns else 0
        st.metric("Com Punição Registrada", int(punidos))

    st.divider()

    st.markdown(f"### Registros ({len(df_filtrado)} encontrados)")
    st.dataframe(df_filtrado, width='stretch')

    csv = df_filtrado.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="📥 Baixar Relatório Consolidado em CSV",
        data=csv,
        file_name=f"relatorio_efetivo_{aba_selecionada.lower().replace(' ', '_')}.csv",
        mime='text/csv',
    )

    if not df_filtrado.empty:
        st.divider()
        st.subheader("📊 Análise Gráfica do Efetivo Filtrado")
        
        gcol1, gcol2 = st.columns(2)
        
        with gcol1:
            if "Posto / Graduação" in df_filtrado.columns:
                st.markdown("**Distribuição por Posto / Graduação**")
                contagem_postos = df_filtrado["Posto / Graduação"].value_counts()
                st.bar_chart(contagem_postos)
            else:
                st.info("Coluna 'Posto / Graduação' não encontrada para o gráfico.")
                
        with gcol2:
            if "Quadro" in df_filtrado.columns:
                st.markdown("**Distribuição por Quadro**")
                contagem_quadros = df_filtrado["Quadro"].value_counts()
                st.bar_chart(contagem_quadros)
            else:
                st.info("Coluna 'Quadro' não encontrada para o gráfico.")

    st.divider()
    st.subheader("💬 Chatbot Gerador de Relatórios")
    st.write("Digite o relatório desejado (ex: *faça um relatório de militares por escolaridade*).")

    if "historico_chat" not in st.session_state:
        st.session_state.historico_chat = []

    for mensagem in st.session_state.historico_chat:
        with st.chat_message(mensagem["role"]):
            st.markdown(mensagem["content"])
            if "df" in mensagem and mensagem["df"] is not None:
                st.dataframe(mensagem["df"], width='stretch')
                csv_bytes = mensagem["df"].to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 Baixar Este Relatório em CSV",
                    data=csv_bytes,
                    file_name=mensagem.get("nome_arquivo", "relatorio.csv"),
                    mime="text/csv",
                    key=f"dl_{time.time()}_{hash(mensagem['content'])}"
                )

    pergunta = st.chat_input("Ex.: faça um relatório de militares por OME")

    if pergunta:
        st.session_state.historico_chat.append({"role": "user", "content": pergunta})
        resultado = processar_relatorio_chat(pergunta, df_filtrado)
        
        item_resposta = {
            "role": "assistant",
            "content": resultado["texto"],
            "df": resultado.get("df"),
            "nome_arquivo": resultado.get("nome_arquivo")
        }
        
        st.session_state.historico_chat.append(item_resposta)
        st.rerun()

else:
    st.warning("Não há dados disponíveis para exibir na seleção atual.")

st.divider()
st.caption("Painel de Efetivo • Desenvolvido com Streamlit e Google Sheets API")
