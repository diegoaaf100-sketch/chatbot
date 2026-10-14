import re
import unicodedata

from google import genai
import gspread
import pandas as pd
import plotly.express as px
import streamlit as st

# =========================================================
# CONFIGURAÇÃO DA PÁGINA
# =========================================================

st.set_page_config(
    page_title="Dashboard de Efetivo",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =========================================================
# CONTROLE DE ACESSO POR E-MAIL
# =========================================================

try:
    is_logged_in = st.user.is_logged_in
    email_usuario = str(st.user.get("email", "")).strip().lower()
except Exception:
    is_logged_in = True
    email_usuario = "desenvolvedor@local.com"

if not is_logged_in:
    st.title("📊 Dashboard de Efetivo")
    st.write("Entre com sua conta Google autorizada para continuar.")
    st.button(
        "Entrar com Google",
        on_click=st.login,
        use_container_width=True,
    )
    st.stop()

try:
    emails_autorizados = {
        str(email).strip().lower()
        for email in st.secrets["acesso"]["emails_autorizados"]
        if str(email).strip()
    }
except Exception:
    emails_autorizados = set()

modo_local = email_usuario == "desenvolvedor@local.com"

if not modo_local and (not email_usuario or email_usuario not in emails_autorizados):
    st.title("📊 Dashboard de Efetivo")
    st.error("Acesso restrito. Esta conta Google não está autorizada.")
    st.button("Sair da conta", on_click=st.logout)
    st.stop()

st.sidebar.success(f"Conectado: {email_usuario}")
st.sidebar.button("Sair da conta", on_click=st.logout)

# =========================================================
# APARÊNCIA
# =========================================================

st.markdown(
    """
    <style>
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2rem;
        max-width: 1600px;
    }

    [data-testid="stMetric"] {
        background: var(--secondary-background-color);
        padding: 16px;
        border-radius: 12px;
        border: 1px solid rgba(128,128,128,0.15);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# =========================================================
# NOMES DAS COLUNAS DA PLANILHA
# =========================================================

COL_POSTO = "Posto / Graduação"
COL_MATRICULA = "Matrícula"
COL_NOME = "Nome"
COL_ANO_PEDIDO = "Ano de Requerimento"
COL_ANO_COMPULSORIA = "Ano de Compulsória"
COL_DIAS_PEDIDO = "Dias para Requerimento"
COL_DIAS_COMPULSORIA = "Dias para Compulsória"

# =========================================================
# CONEXÃO COM GOOGLE SHEETS
# =========================================================

@st.cache_data(
    ttl=300,
    show_spinner="Carregando os dados..."
)
def carregar_planilha():
    credenciais = gspread.service_account_from_dict(
        dict(st.secrets["google_service_account"])
    )

    spreadsheet_id = st.secrets.get("spreadsheet_id")
    if not spreadsheet_id:
        raise ValueError("A chave 'spreadsheet_id' não foi encontrada no arquivo secrets.toml.")

    planilha = credenciais.open_by_key(spreadsheet_id)

    nome_aba = st.secrets.get(
        "worksheet_name",
        "Página4",
    )

    aba = planilha.worksheet(nome_aba)
    dados = pd.DataFrame(aba.get_all_records())

    return dados


try:
    df = carregar_planilha()

except Exception as erro:
    st.error(
        "Não foi possível carregar a planilha. "
        "Verifique as credenciais do Google, "
        "o ID da planilha (`spreadsheet_id`), o nome da aba "
        "e as permissões de acesso."
    )

    with st.expander("Detalhes técnicos do erro"):
        st.code(str(erro))

    st.stop()


if df.empty:
    st.warning(
        "A planilha foi carregada, mas não contém registros."
    )
    st.stop()

# =========================================================
# FUNÇÕES AUXILIARES
# =========================================================

def extrair_dias(valor):
    if pd.isna(valor):
        return None
    resultado = re.search(r"-?\d+", str(valor))
    if resultado:
        return int(resultado.group())
    return None


def converter_ano(dados, coluna):
    if coluna not in dados.columns:
        return pd.Series(index=dados.index, dtype="float64")
    return pd.to_numeric(dados[coluna], errors="coerce")


def contar_ano(dados, coluna, ano):
    anos = converter_ano(dados, coluna)
    return int((anos == ano).sum())


def contar_prazo(dados, coluna, limite):
    if coluna not in dados.columns:
        return 0
    dias = dados[coluna].apply(extrair_dias)
    return int(((dias >= 0) & (dias <= limite)).sum())


def tabela_anual(dados):
    anos_encontrados = []
    for coluna in [COL_ANO_PEDIDO, COL_ANO_COMPULSORIA]:
        if coluna in dados.columns:
            anos = converter_ano(dados, coluna).dropna()
            anos_encontrados.extend(anos.astype(int).tolist())

    anos_disponiveis = sorted(set(anos_encontrados))
    linhas = []

    for ano in anos_disponiveis:
        pedido = contar_ano(dados, COL_ANO_PEDIDO, ano)
        compulsoria = contar_ano(dados, COL_ANO_COMPULSORIA, ano)
        linhas.append({
            "Ano": ano,
            "Reserva a pedido": pedido,
            "Reserva compulsória": compulsoria,
            "Diferença": abs(pedido - compulsoria),
        })

    return pd.DataFrame(linhas)


# =========================================================
# FILTROS
# =========================================================

st.sidebar.title("Filtros do painel")
st.sidebar.caption("Os filtros afetam os indicadores e os gráficos.")

df_filtrado = df.copy()

if COL_POSTO in df.columns:
    postos = sorted(
        df[COL_POSTO].fillna("Não informado").astype(str).unique().tolist()
    )
    postos_selecionados = st.sidebar.multiselect(
        "Posto / Graduação",
        options=postos,
        default=postos,
    )
    serie_posto = df_filtrado[COL_POSTO].fillna("Não informado").astype(str)
    df_filtrado = df_filtrado[serie_posto.isin(postos_selecionados)]

st.sidebar.divider()
st.sidebar.caption("O chatbot utiliza os filtros selecionados no painel.")

# =========================================================
# CABEÇALHO
# =========================================================

st.title("📊 Dashboard de Efetivo")
st.write("Sistema de análise, acompanhamento e consulta das previsões de reserva.")
st.caption("Dados provenientes da planilha autorizada. O painel apresenta indicadores agregados.")
st.divider()

# =========================================================
# INDICADORES
# =========================================================

total_registros = len(df_filtrado)
pedido_180 = contar_prazo(df_filtrado, COL_DIAS_PEDIDO, 180)
compulsoria_90 = contar_prazo(df_filtrado, COL_DIAS_COMPULSORIA, 90)

matriculas_vazias = 0
if COL_MATRICULA in df_filtrado.columns:
    vazias = (
        df_filtrado[COL_MATRICULA].isna()
        | df_filtrado[COL_MATRICULA].astype(str).str.strip().eq("")
    )
    matriculas_vazias = int(vazias.sum())

m1, m2, m3, m4 = st.columns(4)

m1.metric("Total de registros", f"{total_registros:,}".replace(",", "."))
m2.metric("Reserva a pedido", f"{pedido_180:,}".replace(",", "."), help="Registros previstos para os próximos 180 dias.")
m3.metric("Reserva compulsória", f"{compulsoria_90:,}".replace(",", "."), help="Registros previstos para os próximos 90 dias.")
m4.metric("Matrículas vazias", f"{matriculas_vazias:,}".replace(",", "."))

st.divider()

# =========================================================
# ANÁLISE ANUAL
# =========================================================

st.subheader("Evolução anual das reservas")
anual = tabela_anual(df_filtrado)

if anual.empty:
    st.info("Não há anos válidos nas colunas de previsão para montar a análise anual.")
else:
    anos_opcoes = anual["Ano"].astype(int).tolist()
    anos_selecionados = st.multiselect(
        "Selecione os anos para analisar",
        options=anos_opcoes,
        default=anos_opcoes,
        key="anos_dashboard",
    )

    anual_selecionada = anual[anual["Ano"].isin(anos_selecionados)].copy()

    if anual_selecionada.empty:
        st.info("Selecione pelo menos um ano.")
    else:
        grafico_dados = anual_selecionada.melt(
            id_vars=["Ano"],
            value_vars=["Reserva a pedido", "Reserva compulsória"],
            var_name="Tipo de reserva",
            value_name="Quantidade",
        )

        grafico = px.bar(
            grafico_dados,
            x="Ano",
            y="Quantidade",
            color="Tipo de reserva",
            barmode="group",
            text="Quantidade",
            title="Comparação das previsões por ano",
            labels={
                "Ano": "Ano previsto",
                "Quantidade": "Quantidade de registros",
                "Tipo de reserva": "Categoria",
            },
        )

        grafico.update_layout(
            legend_title_text="Tipo de reserva",
            xaxis_type="category",
            hovermode="x unified",
        )

        st.plotly_chart(grafico, use_container_width=True)

        st.markdown("#### Tabela anual")
        st.dataframe(anual_selecionada, hide_index=True, use_container_width=True)

        csv = anual_selecionada.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "Exportar resumo anual para CSV",
            data=csv,
            file_name="resumo_anual_reservas.csv",
            mime="text/csv",
            use_container_width=True,
        )

st.divider()

# =========================================================
# DISTRIBUIÇÃO POR POSTO / GRADUAÇÃO
# =========================================================

st.subheader("Distribuição por posto / graduação")

if COL_POSTO in df_filtrado.columns:
    distribuicao = (
        df_filtrado[COL_POSTO]
        .fillna("Não informado")
        .astype(str)
        .value_counts()
        .rename_axis("Posto / Graduação")
        .reset_index(name="Quantidade")
    )

    grafico_posto = px.bar(
        distribuicao,
        x="Posto / Graduação",
        y="Quantidade",
        text="Quantidade",
        title="Quantidade de registros por posto/graduação",
    )
    grafico_posto.update_layout(xaxis_title="Posto / Graduação", yaxis_title="Quantidade")
    st.plotly_chart(grafico_posto, use_container_width=True)
else:
    st.info("A coluna de posto/graduação não foi encontrada.")

st.divider()

# =========================================================
# CHATBOT COM GEMINI INTELIGENTE
# =========================================================

try:
    gemini_client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
except Exception:
    gemini_client = None


def responder_chatbot(pergunta, dados):
    if not gemini_client:
        return "Erro: A chave 'GEMINI_API_KEY' não foi configurada no arquivo secrets.toml."

    resumo_dados = dados.to_markdown(index=False)

    prompt_sistema = f"""
    Você é um assistente virtual especialista em análise de efetivo e previsões de reserva militar.
    Você está integrado a um painel do Streamlit.
    Abaixo estão os dados atuais da planilha, que já respeitam os filtros de posto/graduação selecionados pelo usuário:
    
    {resumo_dados}
    
    Instruções:
    - Responda à pergunta do usuário utilizando exclusivamente os dados fornecidos acima.
    - Seja claro, objetivo e profissional.
    - Se a informação solicitada não estiver presente nos dados, informe educadamente que não encontrou o registro.
    """

    try:
        resposta = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[prompt_sistema, f"Pergunta do usuário: {pergunta}"]
        )
        return resposta.text
    except Exception as e:
        return f"Ocorreu um erro ao consultar o Gemini: {str(e)}"


st.subheader("💬 Chatbot de consulta com Gemini")
st.write("Faça perguntas livres sobre os dados. O chatbot considera automaticamente os filtros da barra lateral.")

if "historico_chat" not in st.session_state:
    st.session_state.historico_chat = []

for mensagem in st.session_state.historico_chat:
    with st.chat_message(mensagem["role"]):
        st.markdown(mensagem["content"])

pergunta = st.chat_input("Ex.: Quantos registros temos para o ano de 2027?")

if pergunta:
    st.session_state.historico_chat.append({"role": "user", "content": pergunta})
    with st.chat_message("user"):
        st.markdown(pergunta)

    resposta = responder_chatbot(pergunta, df_filtrado)

    st.session_state.historico_chat.append({"role": "assistant", "content": resposta})
    with st.chat_message("assistant"):
        st.markdown(resposta)

    st.rerun()

# =========================================================
# RODAPÉ
# =========================================================

st.divider()
st.caption("Dashboard de Efetivo | Consultas inteligentes via Gemini | Dados atualizados conforme a leitura da planilha.")
