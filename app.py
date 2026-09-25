"""
Controle de Ponto
------------------
Aplicação Streamlit para importar comprovantes de registro de ponto (PDF),
extrair automaticamente a data/hora de cada marcação via OCR, armazenar em
um banco SQLite local e calcular o banco de horas (saldo positivo/negativo).

Como rodar:
    pip install -r requirements.txt
    streamlit run app.py

Requer os binários de sistema `tesseract-ocr` e `poppler-utils` instalados
(ver README.md e o painel de diagnóstico na barra lateral do app).
"""

import io
import re
import shutil
import sqlite3
from datetime import date, datetime

import pandas as pd
import streamlit as st

DB_PATH = "ponto.db"

# ----------------------------------------------------------------------------
# Banco de dados
# ----------------------------------------------------------------------------

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS registros (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT NOT NULL,        -- YYYY-MM-DD
            hora TEXT NOT NULL,        -- HH:MM
            origem TEXT,               -- nome do arquivo ou 'manual'
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(data, hora)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS config (
            chave TEXT PRIMARY KEY,
            valor TEXT
        )
    """)
    conn.commit()
    return conn


def get_config(conn, chave, default=None):
    row = conn.execute("SELECT valor FROM config WHERE chave=?", (chave,)).fetchone()
    return row[0] if row else default


def set_config(conn, chave, valor):
    conn.execute(
        "INSERT INTO config (chave, valor) VALUES (?, ?) "
        "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor",
        (chave, valor),
    )
    conn.commit()


def inserir_registro(conn, data_str, hora_str, origem):
    try:
        conn.execute(
            "INSERT INTO registros (data, hora, origem) VALUES (?, ?, ?)",
            (data_str, hora_str, origem),
        )
        conn.commit()
        return True, None
    except sqlite3.IntegrityError:
        return False, "Já existe uma marcação igual (mesma data e hora)."
    except Exception as e:
        return False, str(e)


def carregar_registros(conn):
    return pd.read_sql_query(
        "SELECT id, data, hora, origem FROM registros ORDER BY data, hora", conn
    )


def excluir_registro(conn, reg_id):
    conn.execute("DELETE FROM registros WHERE id=?", (reg_id,))
    conn.commit()


# ----------------------------------------------------------------------------
# Diagnóstico do ambiente (tesseract / poppler)
# ----------------------------------------------------------------------------

def diagnosticar_ambiente():
    """Verifica se as dependências de OCR estão disponíveis e retorna uma
    lista de (ok: bool, mensagem: str)."""
    resultados = []

    try:
        import pdfplumber  # noqa: F401
        resultados.append((True, "pdfplumber instalado (extração direta de texto)."))
    except ImportError:
        resultados.append((False, "pdfplumber NÃO instalado — rode: pip install pdfplumber"))

    if shutil.which("pdftoppm") or shutil.which("pdftocairo"):
        resultados.append((True, "Poppler encontrado (conversão de PDF em imagem)."))
    else:
        resultados.append((False,
            "Poppler NÃO encontrado no PATH — necessário para o OCR. "
            "Instale: Linux `sudo apt install poppler-utils` | "
            "macOS `brew install poppler` | "
            "Windows: baixe o poppler e adicione a pasta bin ao PATH."))

    if shutil.which("tesseract"):
        resultados.append((True, "Tesseract OCR encontrado."))
    else:
        resultados.append((False,
            "Tesseract OCR NÃO encontrado no PATH — necessário para ler comprovantes "
            "que são imagem (sem texto embutido). Instale: Linux `sudo apt install "
            "tesseract-ocr` | macOS `brew install tesseract` | Windows: baixe o "
            "instalador do Tesseract e adicione a pasta ao PATH."))

    try:
        import pytesseract  # noqa: F401
        resultados.append((True, "pytesseract instalado."))
    except ImportError:
        resultados.append((False, "pytesseract NÃO instalado — rode: pip install pytesseract"))

    try:
        import pdf2image  # noqa: F401
        resultados.append((True, "pdf2image instalado."))
    except ImportError:
        resultados.append((False, "pdf2image NÃO instalado — rode: pip install pdf2image"))

    return resultados


# ----------------------------------------------------------------------------
# Extração de data/hora do comprovante em PDF
# ----------------------------------------------------------------------------

class ErroLeituraPDF(Exception):
    pass


def _regex_data_hora(texto):
    m = re.search(r"Data:\s*(\d{2})/(\d{2})/(\d{4}).{0,40}?(\d{1,2}):(\d{2})", texto)
    if not m:
        return None, None
    dia, mes, ano, hh, mm = m.groups()
    return f"{ano}-{mes}-{dia}", f"{int(hh):02d}:{mm}"


def extrair_texto_direto(pdf_bytes):
    """Tenta extrair texto embutido no PDF (sem OCR). Retorna '' se não houver."""
    import pdfplumber
    texto = ""
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for pagina in pdf.pages:
            texto += (pagina.extract_text() or "") + "\n"
    return texto


def extrair_texto_ocr(pdf_bytes):
    """Converte o PDF em imagem e roda OCR. Levanta ErroLeituraPDF com mensagem
    amigável se poppler/tesseract não estiverem disponíveis."""
    try:
        from pdf2image import convert_from_bytes
    except ImportError:
        raise ErroLeituraPDF(
            "A biblioteca 'pdf2image' não está instalada. Rode: pip install pdf2image"
        )
    try:
        import pytesseract
    except ImportError:
        raise ErroLeituraPDF(
            "A biblioteca 'pytesseract' não está instalada. Rode: pip install pytesseract"
        )

    try:
        paginas = convert_from_bytes(pdf_bytes, dpi=300)
    except Exception as e:
        msg = str(e)
        if "poppler" in msg.lower() or "Unable to get page count" in msg:
            raise ErroLeituraPDF(
                "O Poppler não foi encontrado no sistema (necessário para converter o "
                "PDF em imagem). Instale-o e reinicie o app — veja o README ou o "
                "diagnóstico na barra lateral."
            )
        raise ErroLeituraPDF(f"Falha ao converter o PDF em imagem: {msg}")

    try:
        textos = [pytesseract.image_to_string(p, config="--psm 6") for p in paginas]
    except Exception as e:
        msg = str(e)
        if "tesseract is not installed" in msg.lower() or "not in your path" in msg.lower():
            raise ErroLeituraPDF(
                "O Tesseract OCR não foi encontrado no sistema. Instale-o e reinicie "
                "o app — veja o README ou o diagnóstico na barra lateral."
            )
        raise ErroLeituraPDF(f"Falha ao rodar OCR: {msg}")

    return "\n".join(textos)


def extrair_data_hora_pdf(pdf_bytes):
    """
    Estratégia: primeiro tenta ler texto embutido no PDF (rápido, sem
    dependências externas). Se não achar data/hora, cai para OCR.
    Sempre retorna (data, hora, aviso, texto_bruto) — os dois últimos podem ser None.
    """
    try:
        texto = extrair_texto_direto(pdf_bytes)
    except Exception:
        texto = ""

    data_val, hora_val = _regex_data_hora(texto) if texto else (None, None)
    if data_val and hora_val:
        return data_val, hora_val, None, None

    texto_ocr = extrair_texto_ocr(pdf_bytes)  # pode levantar ErroLeituraPDF
    data_val, hora_val = _regex_data_hora(texto_ocr)
    if not (data_val and hora_val):
        aviso = (
            "Não foi possível localizar automaticamente a data/hora neste "
            "comprovante. Confira o texto reconhecido abaixo e preencha manualmente."
        )
        return None, None, aviso, texto_ocr
    return data_val, hora_val, None, None


# ----------------------------------------------------------------------------
# Cálculo do banco de horas
# ----------------------------------------------------------------------------

DIAS_SEMANA = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


def jornada_padrao_por_dia():
    """Segunda a quinta = 10h, sexta = 9h, fim de semana = 0h."""
    return {0: 600, 1: 600, 2: 600, 3: 600, 4: 540, 5: 0, 6: 0}


def carregar_jornada_por_dia(conn):
    import json
    bruto = get_config(conn, "jornada_por_dia")
    if not bruto:
        return jornada_padrao_por_dia()
    try:
        salvo = json.loads(bruto)
        return {int(k): int(v) for k, v in salvo.items()}
    except Exception:
        return jornada_padrao_por_dia()


def salvar_jornada_por_dia(conn, jornada_por_dia):
    import json
    set_config(conn, "jornada_por_dia", json.dumps(jornada_por_dia))


def calcular_banco_horas(df, jornada_por_dia):
    """
    Para cada dia, ordena os horários e faz o pareamento sequencial
    (1º=entrada, 2º=saída, 3º=entrada, 4º=saída, ...).
    A jornada esperada varia conforme o dia da semana (jornada_por_dia).
    Retorna um DataFrame diário com minutos trabalhados, esperados e saldo.
    """
    if df.empty:
        return pd.DataFrame(columns=[
            "data", "marcacoes", "trabalhado_min", "esperado_min",
            "saldo_min", "saldo_acumulado_min", "incompleto"
        ])

    linhas = []
    for dia, grupo in df.groupby("data"):
        horarios = sorted(grupo["hora"].tolist())
        minutos = [int(h[:2]) * 60 + int(h[3:5]) for h in horarios]

        trabalhado = 0
        incompleto = len(minutos) % 2 == 1
        for i in range(0, len(minutos) - 1, 2):
            trabalhado += minutos[i + 1] - minutos[i]

        data_dt = datetime.strptime(dia, "%Y-%m-%d").date()
        esperado = jornada_por_dia.get(data_dt.weekday(), 0)

        linhas.append({
            "data": dia,
            "marcacoes": " / ".join(horarios),
            "trabalhado_min": trabalhado,
            "esperado_min": esperado,
            "saldo_min": trabalhado - esperado,
            "incompleto": incompleto,
        })

    resultado = pd.DataFrame(linhas).sort_values("data").reset_index(drop=True)
    resultado["saldo_acumulado_min"] = resultado["saldo_min"].cumsum()
    return resultado


def fmt_min(minutos):
    """Formata minutos (podendo ser negativo) como '+HH:MM' / '-HH:MM'."""
    sinal = "-" if minutos < 0 else "+"
    minutos = abs(int(minutos))
    return f"{sinal}{minutos // 60:02d}:{minutos % 60:02d}"


def fmt_min_abs(minutos):
    minutos = int(minutos)
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


# ----------------------------------------------------------------------------
# Interface Streamlit
# ----------------------------------------------------------------------------

st.set_page_config(page_title="Controle de Ponto", page_icon="", layout="wide")
conn = get_conn()

st.title("Controle de Ponto e Banco de Horas")

with st.sidebar:
    st.header("Configurações")
    st.caption("Jornada esperada por dia da semana (HH:MM). Use 00:00 para dias sem expediente.")

    jornada_atual = carregar_jornada_por_dia(conn)
    tabela_jornada = pd.DataFrame({
        "Dia": DIAS_SEMANA,
        "Horas esperadas": [fmt_min_abs(jornada_atual.get(i, 0)) for i in range(7)],
    })
    tabela_editada = st.data_editor(
        tabela_jornada, hide_index=True, use_container_width=True,
        disabled=["Dia"], key="editor_jornada",
    )

    if st.button("Salvar configuração"):
        nova_jornada = {}
        erro_formato = False
        for i, valor in enumerate(tabela_editada["Horas esperadas"]):
            try:
                h, m = str(valor).split(":")
                nova_jornada[i] = int(h) * 60 + int(m)
            except Exception:
                erro_formato = True
        if erro_formato:
            st.error("Use o formato HH:MM em todas as linhas (ex.: 09:00).")
        else:
            salvar_jornada_por_dia(conn, nova_jornada)
            st.success("Configuração salva.")
            st.rerun()

    jornada_por_dia = carregar_jornada_por_dia(conn)

    with st.expander("Diagnóstico do sistema (leitura de PDF)"):
        for ok, msg in diagnosticar_ambiente():
            (st.success if ok else st.error)(msg)

tab_importar, tab_registros, tab_banco = st.tabs(
    ["Importar comprovantes", "Registros", "Banco de horas"]
)

# --- Aba: Importar -----------------------------------------------------------
with tab_importar:
    st.subheader("Importar comprovantes em PDF")
    st.caption(
        "Envie um ou mais comprovantes de registro de ponto. A data e a hora da "
        "marcação são lidas automaticamente. Confira antes de salvar."
    )

    arquivos = st.file_uploader(
        "Comprovantes (PDF)", type=["pdf"], accept_multiple_files=True
    )

    if arquivos:
        if "extraidos" not in st.session_state:
            st.session_state["extraidos"] = {}

        for arq in arquivos:
            if arq.name not in st.session_state["extraidos"]:
                with st.spinner(f"Lendo {arq.name}..."):
                    resultado = {}
                    try:
                        data_val, hora_val, aviso, texto_bruto = extrair_data_hora_pdf(arq.getvalue())
                        resultado["data"] = data_val
                        resultado["hora"] = hora_val
                        resultado["aviso"] = aviso
                        resultado["texto_bruto"] = texto_bruto
                    except ErroLeituraPDF as e:
                        resultado["erro"] = str(e)
                    except Exception as e:
                        resultado["erro"] = f"Erro inesperado ao ler o arquivo: {e}"
                st.session_state["extraidos"][arq.name] = resultado

        for nome_arq, campos in list(st.session_state["extraidos"].items()):
            with st.expander(f" {nome_arq}", expanded=True):
                if campos.get("erro"):
                    st.error(campos["erro"])
                    st.caption(
                        "Confira o painel 'Diagnóstico do sistema' na barra lateral, "
                        "ou preencha a marcação manualmente abaixo."
                    )
                if campos.get("aviso"):
                    st.warning(campos["aviso"])
                    if campos.get("texto_bruto"):
                        with st.popover("Ver texto reconhecido no PDF"):
                            st.text(campos["texto_bruto"])

                col1, col2 = st.columns(2)
                try:
                    data_default = (
                        datetime.strptime(campos.get("data"), "%Y-%m-%d").date()
                        if campos.get("data") else date.today()
                    )
                except Exception:
                    data_default = date.today()
                data_val = col1.date_input("Data", value=data_default, key=f"data_{nome_arq}")
                hora_val = col2.text_input("Hora (HH:MM)", value=campos.get("hora") or "", key=f"hora_{nome_arq}")

                if st.button(" Salvar esta marcação", key=f"salvar_{nome_arq}"):
                    if not re.match(r"^\d{1,2}:\d{2}$", hora_val.strip() or ""):
                        st.error("Informe a hora no formato HH:MM antes de salvar.")
                    else:
                        hh, mm = hora_val.strip().split(":")
                        hora_norm = f"{int(hh):02d}:{mm}"
                        ok, erro = inserir_registro(
                            conn, data_val.strftime("%Y-%m-%d"), hora_norm, origem=nome_arq
                        )
                        if ok:
                            st.success("Marcação salva!")
                            del st.session_state["extraidos"][nome_arq]
                            st.rerun()
                        else:
                            st.error(erro)

    st.divider()
    st.subheader("Ou adicionar uma marcação manualmente")
    with st.form("form_manual"):
        c1, c2 = st.columns(2)
        m_data = c1.date_input("Data", value=date.today())
        m_hora = c2.time_input("Hora")
        if st.form_submit_button("Adicionar marcação"):
            ok, erro = inserir_registro(
                conn, m_data.strftime("%Y-%m-%d"), m_hora.strftime("%H:%M"), origem="manual"
            )
            if ok:
                st.success("Marcação adicionada!")
                st.rerun()
            else:
                st.error(erro)

# --- Aba: Registros ------------------------------------------------------------
with tab_registros:
    st.subheader("Todas as marcações")
    df = carregar_registros(conn)
    if df.empty:
        st.info("Nenhuma marcação cadastrada ainda. Importe um comprovante na aba anterior.")
    else:
        st.dataframe(df.drop(columns=["id"]), use_container_width=True, hide_index=True)

        st.markdown("**Excluir uma marcação**")
        opcoes = {f"#{r.id} — {r.data} {r.hora}": r.id for r in df.itertuples()}
        escolhido = st.selectbox("Selecione a marcação", list(opcoes.keys()))
        if st.button("Excluir"):
            excluir_registro(conn, opcoes[escolhido])
            st.success("Marcação excluída.")
            st.rerun()

# --- Aba: Banco de horas --------------------------------------------------------
with tab_banco:
    st.subheader("Banco de horas")
    df = carregar_registros(conn)
    resumo = calcular_banco_horas(df, jornada_por_dia)

    if resumo.empty:
        st.info("Sem marcações suficientes para calcular o banco de horas.")
    else:
        saldo_final = resumo["saldo_acumulado_min"].iloc[-1]
        col1, col2, col3 = st.columns(3)
        col1.metric("Saldo acumulado", fmt_min(saldo_final))
        col2.metric("Dias com marcação", len(resumo))
        col3.metric("Dias incompletos (nº ímpar de marcações)", int(resumo["incompleto"].sum()))

        tabela = resumo.copy()
        tabela["Trabalhado"] = tabela["trabalhado_min"].apply(fmt_min_abs)
        tabela["Esperado"] = tabela["esperado_min"].apply(fmt_min_abs)
        tabela["Saldo do dia"] = tabela["saldo_min"].apply(fmt_min)
        tabela["Saldo acumulado"] = tabela["saldo_acumulado_min"].apply(fmt_min)
        tabela["Marcações"] = tabela["marcacoes"]
        tabela["Incompleto"] = tabela["incompleto"].map({True: "⚠️ sim", False: ""})

        st.dataframe(
            tabela[["data", "Marcações", "Trabalhado", "Esperado", "Saldo do dia", "Saldo acumulado", "Incompleto"]]
            .rename(columns={"data": "Data"}),
            use_container_width=True, hide_index=True,
        )

        st.markdown("**Evolução do saldo acumulado**")
        chart_df = resumo.set_index("data")[["saldo_acumulado_min"]].rename(
            columns={"saldo_acumulado_min": "Saldo acumulado (min)"}
        )
        st.line_chart(chart_df)

        csv = tabela[["data", "Marcações", "Trabalhado", "Esperado", "Saldo do dia", "Saldo acumulado"]].to_csv(index=False).encode("utf-8")
        st.download_button("Baixar resumo em CSV", csv, file_name="banco_de_horas.csv", mime="text/csv")