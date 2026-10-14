
import re
import unicodedata

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

# Exigir login com Google
if not st.user.is_logged_in:
    st.title("📊 Dashboard de Efetivo")
    st.write(
        "Entre com sua conta Google autorizada para continuar."
    )

    st.button(
        "Entrar com Google",
        on_click=st.login,
        width="stretch",
    )

    st.stop()

# Conferir a lista de e-mails autorizados
emails_autorizados = {
    str(email).strip().lower()
    for email in st.secrets["acesso"]["emails_autorizados"]
    if str(email).strip()
}

# Identificar o usuário conectado
email_usuario = str(
    st.user.get("email", "")
).strip().lower()

# Bloquear usuários não autorizados
if (
    not email_usuario
    or email_usuario not in emails_autorizados
):
    st.title("📊 Dashboard de Efetivo")

    st.error(
        "Acesso restrito. "
        "Esta conta Google não está autorizada."
    )

    st.button(
        "Sair da conta",
        on_click=st.logout,
    )

    st.stop()

# Usuário autorizado
st.sidebar.success(
    f"Conectado: {email_usuario}"
)

st.sidebar.button(
    "Sair da conta",
    on_click=st.logout,
)

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

    planilha = credenciais.open_by_key(
        st.secrets["spreadsheet_id"]
    )

    nome_aba = st.secrets.get(
        "worksheet_name",
        "Página4",
    )

    aba = planilha.worksheet(nome_aba)

    dados = pd.DataFrame(
        aba.get_all_records()
    )

    return dados


try:
    df = carregar_planilha()

except Exception as erro:
    st.error(
        "Não foi possível carregar a planilha. "
        "Verifique as credenciais do Google, "
        "o ID da planilha, o nome da aba "
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

def normalizar(texto):
    texto = str(texto).lower().strip()

    texto = unicodedata.normalize(
        "NFKD",
        texto,
    )

    texto = "".join(
        caractere
        for caractere in texto
        if not unicodedata.combining(caractere)
    )

    texto = re.sub(
        r"[^\w\s/-]",
        " ",
        texto,
    )

    return re.sub(
        r"\s+",
        " ",
        texto,
    ).strip()


def extrair_dias(valor):
    if pd.isna(valor):
        return None

    resultado = re.search(
        r"-?\d+",
        str(valor),
    )

    if resultado:
        return int(resultado.group())

    return None


def coluna_existe(dados, coluna):
    return coluna in dados.columns


def converter_ano(dados, coluna):
    if coluna not in dados.columns:
        return pd.Series(
            index=dados.index,
            dtype="float64",
        )

    return pd.to_numeric(
        dados[coluna],
        errors="coerce",
    )


def contar_ano(dados, coluna, ano):
    anos = converter_ano(
        dados,
        coluna,
    )

    return int(
        (anos == ano).sum()
    )


def contar_prazo(dados, coluna, limite):
    if coluna not in dados.columns:
        return 0

    dias = dados[coluna].apply(
        extrair_dias
    )

    return int(
        ((dias >= 0) & (dias <= limite)).sum()
    )


def tabela_anual(dados):
    anos_encontrados = []

    for coluna in [
        COL_ANO_PEDIDO,
        COL_ANO_COMPULSORIA,
    ]:
        if coluna in dados.columns:
            anos = converter_ano(
                dados,
                coluna,
            ).dropna()

            anos_encontrados.extend(
                anos.astype(int).tolist()
            )

    anos_disponiveis = sorted(
        set(anos_encontrados)
    )

    linhas = []

    for ano in anos_disponiveis:
        pedido = contar_ano(
            dados,
            COL_ANO_PEDIDO,
            ano,
        )

        compulsoria = contar_ano(
            dados,
            COL_ANO_COMPULSORIA,
            ano,
        )

        linhas.append({
            "Ano": ano,
            "Reserva a pedido": pedido,
            "Reserva compulsória": compulsoria,
            "Diferença": abs(
                pedido - compulsoria
            ),
        })

    return pd.DataFrame(linhas)


# =========================================================
# FILTROS
# =========================================================

st.sidebar.title("Filtros do painel")

st.sidebar.caption(
    "Os filtros afetam os indicadores e os gráficos."
)

df_filtrado = df.copy()

if COL_POSTO in df.columns:
    postos = (
        df[COL_POSTO]
        .fillna("Não informado")
        .astype(str)
        .unique()
        .tolist()
    )

    postos = sorted(postos)

    postos_selecionados = st.sidebar.multiselect(
        "Posto / Graduação",
        options=postos,
        default=postos,
    )

    serie_posto = (
        df_filtrado[COL_POSTO]
        .fillna("Não informado")
        .astype(str)
    )

    df_filtrado = df_filtrado[
        serie_posto.isin(
            postos_selecionados
        )
    ]

st.sidebar.divider()

st.sidebar.caption(
    "O chatbot utiliza os filtros selecionados no painel."
)

# =========================================================
# CABEÇALHO
# =========================================================

st.title("📊 Dashboard de Efetivo")

st.write(
    "Sistema de análise, acompanhamento e consulta "
    "das previsões de reserva."
)

st.caption(
    "Dados provenientes da planilha autorizada. "
    "O painel apresenta indicadores agregados."
)

st.divider()

# =========================================================
# INDICADORES
# =========================================================

total_registros = len(df_filtrado)

pedido_180 = contar_prazo(
    df_filtrado,
    COL_DIAS_PEDIDO,
    180,
)

compulsoria_90 = contar_prazo(
    df_filtrado,
    COL_DIAS_COMPULSORIA,
    90,
)

matriculas_vazias = 0

if COL_MATRICULA in df_filtrado.columns:
    vazias = (
        df_filtrado[COL_MATRICULA].isna()
        | df_filtrado[COL_MATRICULA]
        .astype(str)
        .str.strip()
        .eq("")
    )

    matriculas_vazias = int(
        vazias.sum()
    )

m1, m2, m3, m4 = st.columns(4)

m1.metric(
    "Total de registros",
    f"{total_registros:,}".replace(",", "."),
)

m2.metric(
    "Reserva a pedido",
    f"{pedido_180:,}".replace(",", "."),
    help="Registros previstos para os próximos 180 dias.",
)

m3.metric(
    "Reserva compulsória",
    f"{compulsoria_90:,}".replace(",", "."),
    help="Registros previstos para os próximos 90 dias.",
)

m4.metric(
    "Matrículas vazias",
    f"{matriculas_vazias:,}".replace(",", "."),
)

st.divider()

# =========================================================
# ANÁLISE ANUAL
# =========================================================

st.subheader(
    "Evolução anual das reservas"
)

anual = tabela_anual(
    df_filtrado
)

if anual.empty:
    st.info(
        "Não há anos válidos nas colunas de previsão "
        "para montar a análise anual."
    )

else:
    anos_opcoes = (
        anual["Ano"]
        .astype(int)
        .tolist()
    )

    anos_selecionados = st.multiselect(
        "Selecione os anos para analisar",
        options=anos_opcoes,
        default=anos_opcoes,
        key="anos_dashboard",
    )

    anual_selecionada = anual[
        anual["Ano"].isin(
            anos_selecionados
        )
    ].copy()

    if anual_selecionada.empty:
        st.info(
            "Selecione pelo menos um ano."
        )

    else:
        grafico_dados = anual_selecionada.melt(
            id_vars=["Ano"],
            value_vars=[
                "Reserva a pedido",
                "Reserva compulsória",
            ],
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

        st.plotly_chart(
            grafico,
            width="stretch",
        )

        st.markdown(
            "#### Tabela anual"
        )

        st.dataframe(
            anual_selecionada,
            hide_index=True,
            width="stretch",
        )

        csv = anual_selecionada.to_csv(
            index=False
        ).encode("utf-8-sig")

        st.download_button(
            "Exportar resumo anual para CSV",
            data=csv,
            file_name="resumo_anual_reservas.csv",
            mime="text/csv",
            width="stretch",
        )

        idx_pedido = anual_selecionada[
            "Reserva a pedido"
        ].idxmax()

        idx_compulsoria = anual_selecionada[
            "Reserva compulsória"
        ].idxmax()

        ano_pedido = int(
            anual_selecionada.loc[
                idx_pedido,
                "Ano",
            ]
        )

        valor_pedido = int(
            anual_selecionada.loc[
                idx_pedido,
                "Reserva a pedido",
            ]
        )

        ano_compulsoria = int(
            anual_selecionada.loc[
                idx_compulsoria,
                "Ano",
            ]
        )

        valor_compulsoria = int(
            anual_selecionada.loc[
                idx_compulsoria,
                "Reserva compulsória",
            ]
        )

        c1, c2 = st.columns(2)

        c1.info(
            f"Maior previsão de reserva a pedido: "
            f"{ano_pedido} ({valor_pedido} registros)."
        )

        c2.info(
            f"Maior previsão de reserva compulsória: "
            f"{ano_compulsoria} ({valor_compulsoria} registros)."
        )

st.divider()

# =========================================================
# DISTRIBUIÇÃO POR POSTO / GRADUAÇÃO
# =========================================================

st.subheader(
    "Distribuição por posto / graduação"
)

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
        title=(
            "Quantidade de registros por posto/graduação"
        ),
    )

    grafico_posto.update_layout(
        xaxis_title="Posto / Graduação",
        yaxis_title="Quantidade",
    )

    st.plotly_chart(
        grafico_posto,
        width="stretch",
    )

else:
    st.info(
        "A coluna de posto/graduação não foi encontrada."
    )

st.divider()

# =========================================================
# CHATBOT LOCAL
# =========================================================

def responder_chatbot(pergunta, dados):
    t = normalizar(pergunta)

    # Comparação anual
    ano_match = re.search(
        r"\b(20\d{2})\b",
        t,
    )

    comparar = any(
        palavra in t
        for palavra in [
            "comparar",
            "comparativo",
            "compare",
            "comparacao",
            "diferenca",
            "qual tipo",
            "maior quantidade",
            "qual categoria",
        ]
    )

    if ano_match and comparar:
        ano = int(
            ano_match.group(1)
        )

        pedido = contar_ano(
            dados,
            COL_ANO_PEDIDO,
            ano,
        )

        compulsoria = contar_ano(
            dados,
            COL_ANO_COMPULSORIA,
            ano,
        )

        diferenca = abs(
            pedido - compulsoria
        )

        if pedido > compulsoria:
            maior = "Reserva a pedido"

        elif compulsoria > pedido:
            maior = "Reserva compulsória"

        else:
            maior = (
                "As duas categorias têm a mesma quantidade"
            )

        return (
            f"Comparativo de reservas em {ano}\n\n"
            f"- Reserva a pedido: {pedido}\n"
            f"- Reserva compulsória: {compulsoria}\n"
            f"- Diferença: {diferenca}\n"
            f"- Resultado: {maior}.\n\n"
            "São contagens separadas, não necessariamente "
            "servidores únicos."
        )

    # Tabela anual por intervalo
    intervalo = re.search(
        r"\b(20\d{2})\s+(?:a|ate)\s+(20\d{2})\b",
        t,
    )

    if intervalo and any(
        p in t
        for p in [
            "tabela",
            "resumo",
            "por ano",
        ]
    ):
        inicio = int(
            intervalo.group(1)
        )

        fim = int(
            intervalo.group(2)
        )

        if inicio > fim:
            inicio, fim = fim, inicio

        if fim - inicio > 50:
            return (
                "Consulte um intervalo de até 50 anos por vez."
            )

        linhas = []

        for ano in range(
            inicio,
            fim + 1,
        ):
            pedido = contar_ano(
                dados,
                COL_ANO_PEDIDO,
                ano,
            )

            compulsoria = contar_ano(
                dados,
                COL_ANO_COMPULSORIA,
                ano,
            )

            linhas.append({
                "Ano": ano,
                "Reserva a pedido": pedido,
                "Reserva compulsória": compulsoria,
                "Diferença": abs(
                    pedido - compulsoria
                ),
            })

        tabela = pd.DataFrame(
            linhas
        )

        return tabela.to_markdown(
            index=False
        )

    # Consulta por prazo
    prazo = re.search(
        r"\b(\d+)\s*dias?\b",
        t,
    )

    if prazo and any(
        p in t
        for p in [
            "reserva",
            "proximos",
            "quantos",
            "quantas",
            "servidores",
        ]
    ):
        limite = int(
            prazo.group(1)
        )

        if any(
            p in t
            for p in [
                "a pedido",
                "requerimento",
            ]
        ):
            coluna = COL_DIAS_PEDIDO
            descricao = "reserva a pedido"

        else:
            coluna = COL_DIAS_COMPULSORIA
            descricao = "reserva compulsória"

        quantidade = contar_prazo(
            dados,
            coluna,
            limite,
        )

        return (
            f"Registros de {descricao} previstos nos "
            f"próximos {limite} dias: {quantidade}."
        )

    # Consulta por ano
    if ano_match and any(
        p in t
        for p in [
            "reserva",
            "quantos",
            "quantas",
            "previstos",
        ]
    ):
        ano = int(
            ano_match.group(1)
        )

        if any(
            p in t
            for p in [
                "a pedido",
                "requerimento",
            ]
        ):
            coluna = COL_ANO_PEDIDO
            descricao = "reserva a pedido"

        else:
            coluna = COL_ANO_COMPULSORIA
            descricao = "reserva compulsória"

        quantidade = contar_ano(
            dados,
            coluna,
            ano,
        )

        return (
            f"Registros de {descricao} previstos para "
            f"{ano}: {quantidade}."
        )

    # Distribuição por posto
    if (
        "por posto" in t
        or "por graduacao" in t
    ):
        if COL_POSTO not in dados.columns:
            return (
                "A coluna de posto/graduação não foi encontrada."
            )

        contagem = (
            dados[COL_POSTO]
            .fillna("Não informado")
            .value_counts()
        )

        return "\n".join(
            f"- {categoria}: {quantidade}"
            for categoria, quantidade in contagem.items()
        )

    # Total de registros
    if any(
        p in t
        for p in [
            "total de registros",
            "quantos registros",
            "quantos servidores",
            "total de servidores",
        ]
    ):
        return (
            f"Total de registros no conjunto filtrado: "
            f"{len(dados)}."
        )

    # Média de dias
    if (
        "media" in t
        and "dias" in t
    ):
        if any(
            p in t
            for p in [
                "a pedido",
                "requerimento",
            ]
        ):
            coluna = COL_DIAS_PEDIDO
            descricao = "reserva a pedido"

        else:
            coluna = COL_DIAS_COMPULSORIA
            descricao = "reserva compulsória"

        if coluna not in dados.columns:
            return (
                f"A coluna '{coluna}' não foi encontrada."
            )

        dias = (
            dados[coluna]
            .apply(extrair_dias)
            .dropna()
        )

        if dias.empty:
            return (
                "Não existem dados suficientes "
                "para calcular a média."
            )

        return (
            f"Média de dias restantes para {descricao}: "
            f"{dias.mean():.1f} dias."
        )

    # Campos vazios
    if any(
        p in t
        for p in [
            "vazios",
            "vazias",
            "em branco",
        ]
    ):
        if "matricula" in t:
            coluna = COL_MATRICULA

        elif "nome" in t:
            coluna = COL_NOME

        else:
            return (
                "Informe qual campo deseja verificar."
            )

        if coluna not in dados.columns:
            return (
                f"A coluna '{coluna}' não foi encontrada."
            )

        vazios = (
            dados[coluna].isna()
            | dados[coluna]
            .astype(str)
            .str.strip()
            .eq("")
        )

        return (
            f"Quantidade de campos vazios em '{coluna}': "
            f"{int(vazios.sum())}."
        )

    # Duplicidades, sem revelar valores
    if (
        "matricula" in t
        and any(
            p in t
            for p in [
                "duplicadas",
                "duplicados",
                "repetidas",
                "repetidos",
            ]
        )
    ):
        if COL_MATRICULA not in dados.columns:
            return (
                "A coluna Matrícula não foi encontrada."
            )

        matriculas = (
            dados[COL_MATRICULA]
            .dropna()
            .astype(str)
            .str.strip()
        )

        matriculas = matriculas[
            matriculas != ""
        ]

        quantidade = int(
            matriculas.duplicated().sum()
        )

        return (
            "Quantidade de matrículas repetidas além da "
            f"primeira ocorrência: {quantidade}. "
            "Nenhuma matrícula foi exibida."
        )

    return (
        "Não consegui interpretar essa pergunta. "
        "Tente perguntar sobre prazos, anos, comparativos, "
        "total de registros ou distribuição por posto/graduação."
    )


st.subheader(
    "💬 Chatbot de consulta"
)

st.write(
    "Faça perguntas sobre os dados agregados. "
    "O chatbot considera os filtros de posto/graduação "
    "selecionados."
)

if "historico_chat" not in st.session_state:
    st.session_state.historico_chat = []

for mensagem in st.session_state.historico_chat:
    with st.chat_message(
        mensagem["role"]
    ):
        st.markdown(
            mensagem["content"]
        )

pergunta = st.chat_input(
    "Ex.: Compare as reservas em 2027"
)

if pergunta:
    st.session_state.historico_chat.append({
        "role": "user",
        "content": pergunta,
    })

    with st.chat_message("user"):
        st.markdown(pergunta)

    resposta = responder_chatbot(
        pergunta,
        df_filtrado,
    )

    st.session_state.historico_chat.append({
        "role": "assistant",
        "content": resposta,
    })

    with st.chat_message("assistant"):
        st.markdown(resposta)

    st.rerun()

# =========================================================
# RODAPÉ
# =========================================================

st.divider()

st.caption(
    "Dashboard de Efetivo | Consultas agregadas | "
    "Dados atualizados conforme a leitura da planilha."
)
```
