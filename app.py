import time
import pandas as pd
import streamlit as st

# =========================================================
# FUNÇÕES DE APOIO E RESUMO
# =========================================================

def coluna_por_alias(dados: pd.DataFrame, aliases: list) -> str:
    """Retorna o nome da coluna real existente no DataFrame com base em uma lista de possíveis aliases."""
    for alias in aliases:
        if alias in dados.columns:
            return alias
    return None

def valor_preenchido(serie: pd.Series) -> pd.Series:
    """Verifica se os valores de uma série estão preenchidos (não nulos e diferentes de vazio/espaços)."""
    return serie.notna() & (serie.astype(str).str.strip() != "") & (serie.astype(str).str.lower() != "nan")

def contar_afirmativos(dados: pd.DataFrame, aliases: list) -> int:
    """Conta registros cujo valor preenchido seja afirmativo (Sim, True, 1, etc.)."""
    coluna = coluna_por_alias(dados, aliases)
    if not coluna:
        return 0
    serie = dados[coluna].astype(str).str.strip().str.lower()
    afirmativos = {"sim", "s", "true", "1", "yes"}
    return int(serie.isin(afirmativos).sum())

def contar_preenchidos(dados: pd.DataFrame, aliases: list) -> int:
    """Conta registros com dados preenchidos em uma coluna."""
    coluna = coluna_por_alias(dados, aliases)
    if not coluna:
        return 0
    return int(valor_preenchido(dados[coluna]).sum())

def resumo_agregado_para_chat(dados: pd.DataFrame) -> dict:
    """Gera um dicionário agregado e seguro com distribuições e indicadores para o chatbot."""
    resumo = {
        "distribuicao_posto": {},
        "distribuicao_ome": {},
        "distribuicao_secao": {},
        "distribuicao_quadro": {},
        "indicadores": {},
        "campos_com_vazios": {},
        "anos_de_afastamento": {},
    }

    for rotulo, aliases in [
        ("Posto / Graduação", ["Posto / Graduação", "Posto/Graduação"]),
        ("OME", ["OME"]),
        ("Seção", ["Seção", "Secao"]),
        ("Quadro", ["Quadro"]),
    ]:
        coluna = coluna_por_alias(dados, aliases)
        if coluna:
            contagem = (
                dados[coluna].fillna("Não informado").astype(str)
                .replace("", "Não informado").value_counts().head(30)
            )
            resumo_key = {
                "Posto / Graduação": "distribuicao_posto",
                "OME": "distribuicao_ome",
                "Seção": "distribuicao_secao",
                "Quadro": "distribuicao_quadro",
            }[rotulo]
            resumo[resumo_key] = {str(k): int(v) for k, v in contagem.items()}

    for rotulo, aliases in [
        ("readaptados", ["Militar Readaptado"]),
        ("horario_especial", ["Militar com Horário Especial de Trabalho"]),
        ("afastamento_1", ["Militar em Afastamento (1)"]),
        ("afastamento_2", ["Militar em Afastamento (2)"]),
        ("pcd", ["Militar PCD"]),
        ("acumulacao_cargo", ["Acumulação de Cargo Público"]),
    ]:
        resumo["indicadores"][rotulo] = contar_afirmativos(dados, aliases)

    resumo["indicadores"]["registros_com_punicao_preenchida"] = contar_preenchidos(
        dados, ["Punição", "Punicao"]
    )

    for rotulo, aliases in [
        ("matricula", ["Matrícula", "Matricula"]),
        ("nome", ["Nome completo", "Nome"]),
        ("ome", ["OME"]),
        ("secao", ["Seção", "Secao"]),
        ("email", ["Email", "E-mail"]),
        ("telefone", ["Telefone - 1º Opção (DDD) 9XXXX-XXXX", "Telefone - 1a Opcao (DDD) 9XXXX-XXXX"]),
        ("endereco", ["Endereço", "Endereco"]),
    ]:
        coluna = coluna_por_alias(dados, aliases)
        if coluna:
            resumo["campos_com_vazios"][rotulo] = int((~valor_preenchido(dados[coluna])).sum())

    return resumo


# =========================================================
# CONFIGURAÇÃO DO CLIENTE GEMINI (exemplo de inicialização)
# =========================================================
# Certifique-se de configurar a biblioteca google-genai e o st.secrets corretamente no seu app
import os
from google import genai

api_key = st.secrets.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
gemini_client = genai.Client(api_key=api_key) if api_key else None


def responder_chatbot(pergunta: str, dados: pd.DataFrame) -> str:
    if not gemini_client:
        return (
            "O chatbot inteligente não está configurado. Confira se a chave "
            "GEMINI_API_KEY está definida nos Secrets do Streamlit Cloud."
        )

    resumo = resumo_agregado_para_chat(dados)
    prompt_sistema = f"""
Você é um assistente de análise de efetivo integrado a um dashboard Streamlit.
Responda em português brasileiro, com clareza e objetividade.
Use exclusivamente os indicadores agregados fornecidos abaixo.
Não invente dados. Se a informação não puder ser calculada a partir do resumo,
explique essa limitação e sugira usar os filtros ou a pesquisa do painel.
Nunca solicite nem tente inferir nomes, matrículas, e-mails, telefones,
endereços, números de processos SEI ou detalhes pessoais individuais.
Os dados abaixo contêm somente contagens e distribuições agregadas, sem linhas
individuais nem identificadores pessoais.

Resumo agregado do painel:
{resumo}
"""
    for tentativa in range(2):
        try:
            resposta = gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[prompt_sistema, f"Pergunta do usuário: {pergunta}"],
            )
            texto_resposta = getattr(resposta, "text", None)
            return texto_resposta or "O Gemini não retornou uma resposta textual."
        except Exception as erro:
            erro_texto = str(erro)
            if ("503" in erro_texto or "UNAVAILABLE" in erro_texto.upper()) and tentativa == 0:
                time.sleep(2)
                continue
            if "429" in erro_texto or "RESOURCE_EXHAUSTED" in erro_texto.upper():
                return "O limite de requisições do Gemini foi atingido. Aguarde um pouco e tente novamente."
            if "503" in erro_texto or "UNAVAILABLE" in erro_texto.upper():
                return "O serviço do Gemini está temporariamente indisponível. Tente novamente em instantes."
            return "Não foi possível consultar o Gemini. Confira a configuração da chave e tente novamente."


# =========================================================
# INTERFACE DO STREAMLIT
# =========================================================

st.title("📊 Painel de Gestão de Efetivo")

# (Nota: Certifique-se de que o seu df_filtrado está definido antes deste ponto no seu dashboard principal)
# Exemplo simulado caso teste isolado:
if "df_filtrado" not in st.session_state:
    st.session_state.df_filtrado = pd.DataFrame()

df_filtrado = st.session_state.df_filtrado

st.subheader("💬 Chatbot de consulta com Gemini")
st.write(
    "Faça perguntas sobre totais, distribuições e qualidade do preenchimento. "
    "O chatbot considera a unidade e os filtros selecionados e recebe apenas dados agregados."
)

if "historico_chat" not in st.session_state:
    st.session_state.historico_chat = []

for mensagem in st.session_state.historico_chat:
    with st.chat_message(mensagem["role"]):
        st.markdown(mensagem["content"])

pergunta = st.chat_input(
    "Ex.: Quantos militares estão readaptados nesta unidade?"
)

if pergunta:
    st.session_state.historico_chat.append({"role": "user", "content": pergunta})
    resposta = responder_chatbot(pergunta, df_filtrado)
    st.session_state.historico_chat.append({"role": "assistant", "content": resposta})
    st.rerun()

# =========================================================
# RODAPÉ
# =========================================================
st.divider()
st.caption("Painel de Gestão de Efetivo • Desenvolvido com Streamlit e Google Gemini")
