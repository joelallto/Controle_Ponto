# Controle de Ponto

Aplicativo em Streamlit para importar comprovantes de registro de ponto (PDF),
ler automaticamente a **data e hora** de cada marcação e calcular o
**banco de horas** (saldo positivo/negativo). Só guarda data/hora — nome, PIS
e empresa não são armazenados, já que não mudam.

## O que ele faz

- **Importar comprovantes**: envie o PDF do comprovante (como o que você gera
  ao bater o ponto). O app tenta ler a data/hora primeiro direto do texto do
  PDF e, se o comprovante for uma imagem (sem texto embutido), usa OCR. Você
  confere/corrige antes de salvar.
- **Registros**: lista de todas as marcações salvas, com opção de excluir.
- **Banco de horas**: para cada dia, ordena as marcações e as agrupa em pares
  (1ª = entrada, 2ª = saída, 3ª = entrada, 4ª = saída...), soma o tempo
  trabalhado e compara com a jornada esperada configurada na barra lateral.
  Mostra o saldo do dia e o saldo acumulado (positivo ou negativo), além de
  um gráfico de evolução e exportação em CSV.

Dias com número ímpar de marcações (por exemplo, esqueceu de bater a saída)
ficam marcados como **incompletos** na tabela.

## Instalação

1. Instale o Python 3.9+ e os pacotes do projeto:

   ```bash
   pip install -r requirements.txt
   ```

2. O OCR depende de dois programas do sistema (não são pacotes Python):
   **Tesseract OCR** e **Poppler** (para converter PDF em imagem).

   - **Windows**: instale o Tesseract
     ([instalador aqui](https://github.com/UB-Mannheim/tesseract/wiki)) e o
     Poppler ([binários aqui](https://github.com/oschwartz10612/poppler-windows/releases)),
     e adicione as duas pastas `bin` ao PATH do sistema.
   - **macOS**: `brew install tesseract poppler`
   - **Linux (Debian/Ubuntu)**: `sudo apt install tesseract-ocr poppler-utils`

3. Rode o app:

   ```bash
   streamlit run app.py
   ```

O navegador abrirá automaticamente em `http://localhost:8501`.

## Não está conseguindo ler o PDF?

Abra a barra lateral do app e expanda **"🔧 Diagnóstico do sistema"** — ele
mostra exatamente qual dependência está faltando (Poppler, Tesseract,
pdfplumber, pytesseract ou pdf2image), com o comando de instalação certo para
o seu sistema operacional. As causas mais comuns:

- **`pip install -r requirements.txt` não foi rodado**, ou foi rodado num
  ambiente/virtualenv diferente do que você usa para `streamlit run app.py`.
- **Poppler e/ou Tesseract não estão instalados no sistema** (eles não são
  pacotes Python, precisam ser instalados separadamente — veja "Instalação"
  abaixo). No Windows é comum esquecer de adicionar a pasta `bin` de cada um
  ao PATH e precisar reabrir o terminal depois.
- **O comprovante é uma imagem** (a maioria dos comprovantes de ponto são
  "impressos" em PDF sem texto real embutido) — nesse caso o app precisa do
  OCR (Poppler + Tesseract) funcionando; a extração direta de texto sozinha
  não é suficiente.

Se mesmo com tudo instalado a leitura falhar, o app agora mostra a mensagem
de erro específica na tela (em vez de travar), e você sempre pode preencher a
data/hora manualmente logo abaixo do aviso.

## Onde ficam os dados

Tudo é salvo em um arquivo `ponto.db` (SQLite) na mesma pasta do `app.py`.
Faça backup desse arquivo se quiser preservar o histórico — ele não é
enviado para lugar nenhum, fica só na sua máquina.

## Observações

- Se o OCR não reconhecer algum comprovante (layout diferente, PDF de baixa
  qualidade, etc.), você ainda pode preencher os campos manualmente na tela
  de importação, ou usar o formulário "adicionar marcação manualmente" na
  mesma aba.
- A jornada diária esperada e se sábado/domingo contam como dia esperado são
  configuráveis na barra lateral, a qualquer momento.
