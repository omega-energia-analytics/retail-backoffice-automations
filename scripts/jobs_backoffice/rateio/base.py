"""
Peças compartilhadas pelos leitores de rateio de cada distribuidora.

Cada distribuidora tem seu próprio módulo (cpfl_paulista.py, equatorial_go.py, ...)
que sabe ler o formato de arquivo dela. O contrato é sempre o mesmo: devolver um
DataFrame com as COLUNAS_CANONICAS abaixo, para que o pipeline em
monit_hist_usina.py trate todas as distribuidoras de forma idêntica.
"""

import os

import pandas as pd
from colorama import Fore, Style

# Schema que todo leitor de distribuidora precisa devolver.
COLUNAS_CANONICAS = [
    "Distribuidora",
    "UG",
    "UC",
    "%",
    "Data de Envio",
    "Mês de Envio",
]


def finalizar_rateio(df, distribuidora, data_hoje, mes_envio):
    """
    Carimba os campos padrão (Distribuidora / Data de Envio / Mês de Envio) e
    devolve o DataFrame apenas com as colunas canônicas.

    O `df` de entrada já deve conter UG, UC e % tratados pela distribuidora.
    """
    df = df.copy()
    df["Distribuidora"] = distribuidora
    df["Data de Envio"] = data_hoje
    df["Mês de Envio"] = mes_envio
    return df[COLUNAS_CANONICAS].copy()


def checar_arquivos_baixados(arquivos):
    """
    Garante que o conteúdo dos arquivos está acessível antes de lê-los de fato.

    Arquivos "online-only" do OneDrive com download travado falham com um
    `OSError [Errno 22]` críptico ("a operação na nuvem não foi concluída").
    Aqui tentamos abrir cada arquivo e, se algum não abrir, damos UMA mensagem
    clara listando todos os problemáticos — em vez de estourar no meio do
    processamento, num arquivo só.

    A detecção é por leitura real, NÃO por atributo: o flag RECALL_ON_DATA_ACCESS
    do OneDrive continua setado mesmo em arquivos já baixados e legíveis, então
    checar atributo dava falso-positivo (bloqueava arquivo bom).
    """
    nao_acessiveis = []
    for arq in arquivos:
        try:
            with open(arq, "rb") as fh:
                fh.read(1)
        except OSError:
            nao_acessiveis.append(os.path.basename(str(arq)))

    if nao_acessiveis:
        detalhe = "\n".join(f"  - {nome}" for nome in nao_acessiveis)
        raise FileNotFoundError(
            f"{len(nao_acessiveis)} arquivo(s) não puderam ser abertos — "
            f"provavelmente online-only do OneDrive ou com sincronização "
            f"travada. Clique com o botão direito na pasta e escolha 'Sempre "
            f"manter neste dispositivo'; se persistir, reinicie o OneDrive. "
            f"Depois rode de novo:\n{detalhe}"
        )


def agregar_rateios(listar_arquivos, ler_rateio, folder, data_hoje, mes_envio):
    """
    Loop genérico: lista os arquivos da pasta, lê cada um com a função da
    distribuidora e concatena tudo num único DataFrame canônico.
    """
    arquivos = listar_arquivos(folder)
    checar_arquivos_baixados(arquivos)

    lista = [ler_rateio(arq, data_hoje, mes_envio) for arq in arquivos]

    df = pd.concat(lista, ignore_index=True)

    print("\nSoma de rateio por UG:")
    print(df.groupby("UG")["%"].sum())

    return df


def validar_soma_rateio(df, tolerancia=0.01, bloquear=True):
    """
    Confere se o % de rateio soma ~1.0 (100%) por UG.

    Rateio que não fecha 100% quase sempre é sinal de arquivo torto ou bug de
    leitura (escala de %, linha de "TOTAL" capturada, UC sem match, etc.). Como
    esses erros são silenciosos — não quebram, só geram número errado — esta
    trava serve para pegá-los ANTES de o dado entrar no histórico.

    tolerancia : desvio aceitável em torno de 1.0 (0.01 = ±1 ponto percentual).
    bloquear   : True levanta ValueError e interrompe; False apenas imprime aviso.

    Devolve o próprio df, para poder ser encadeado.
    """
    somas = df.groupby("UG")["%"].sum()
    fora = somas[(somas < 1 - tolerancia) | (somas > 1 + tolerancia)]
    qtd_pct_nan = int(df["%"].isna().sum())

    if len(fora) == 0 and qtd_pct_nan == 0:
        print(
            f"{Fore.GREEN}Validação de rateio OK: "
            f"todas as {somas.size} UG(s) fecham ~1.0 "
            f"(tolerância ±{tolerancia}).{Style.RESET_ALL}"
        )
        return df

    detalhe = "\n".join(
        f"  - UG {ug}: soma {soma:.6f} (desvio {soma - 1:+.6f})"
        for ug, soma in fora.items()
    )

    msg = f"Validação de rateio: {len(fora)} UG(s) fora de 1.0 ± {tolerancia}."
    if detalhe:
        msg += f"\n{detalhe}"
    if qtd_pct_nan:
        msg += (
            f"\n  * {qtd_pct_nan} linha(s) com % não numérico (NaN) — "
            f"confira a coluna de percentual."
        )

    if bloquear:
        raise ValueError(msg)

    print(f"{Fore.YELLOW}ATENÇÃO: {msg}{Style.RESET_ALL}")
    return df
