"""Cria arquivos sintéticos em pasta_teste para testar o Faxineiro à mão.

Só cria arquivos que ainda não existem: nunca sobrescreve nem apaga nada.
Uso: python ferramentas/gerar_amostras.py
"""

from __future__ import annotations

import os
import random
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from faxineiro.config import PASTA_TESTE  # noqa: E402
from tests.conftest import bytes_docx, bytes_jpeg, bytes_pdf, bytes_png, bytes_zip  # noqa: E402


def amostras() -> dict[str, bytes]:
    rnd = random.Random(42)
    arquivos: dict[str, bytes] = {}
    for i in range(1, 11):
        arquivos[f"Fotos/IMG_{i:04d}.png"] = bytes_png() + bytes([i])
    for i in range(1, 6):
        arquivos[f"Fotos/viagem/foto_{i}.jpg"] = bytes_jpeg() + bytes([i])
    arquivos["Fotos/IMG_0001 - Cópia.png"] = bytes_png() + bytes([1])  # duplicado exato
    for i in range(1, 6):
        arquivos[f"Documentos/boleto_{i}.pdf"] = bytes_pdf() + f"% {i}\n".encode()
    arquivos["Documentos/TCC_final.docx"] = bytes_docx()
    arquivos["Documentos/TCC_final_v2.docx"] = bytes_docx()  # duplicado exato
    arquivos["Documentos/anotacoes.txt"] = "Aula de banco de dados: normalização\n".encode() * 20
    arquivos["Documentos/planilha.csv"] = b"nome;valor\narroz;10\nfeijao;8\n"
    arquivos["Downloads/instalador.zip"] = bytes_zip({"leiame.txt": b"instale"})
    arquivos["Downloads/foto_whatsapp.jpg"] = bytes_png()  # extensão errada (é PNG)
    arquivos["Downloads/arquivo_sem_extensao"] = bytes_pdf()  # PDF sem extensão
    arquivos["Downloads/video_grande.bin"] = bytes(rnd.getrandbits(8) for _ in range(2 * 1024 * 1024))
    arquivos["Downloads/vazio.txt"] = b""
    for i in range(1, 6):
        arquivos[f"Diversos/rascunho_{i}.md"] = f"# Rascunho {i}\nideias soltas\n".encode()
    arquivos["_quarentena/nao_deve_ser_indexado.txt"] = b"pasta bloqueada"
    # Fase 2 (Raio-X)
    filme = bytes(rnd.getrandbits(8) for _ in range(3 * 1024 * 1024))
    arquivos["Videos/filme_ferias.mp4.bin"] = filme
    arquivos["Downloads/filme_ferias (1).mp4.bin"] = filme  # duplicado grande
    quase = bytes(rnd.getrandbits(8) for _ in range(1024 * 1024))
    arquivos["Videos/gravacao_parte1.bin"] = quase + b"A"  # mesmo tamanho e começo,
    arquivos["Videos/gravacao_parte2.bin"] = quase + b"B"  # mas NÃO são duplicados
    arquivos["Documentos/~$TCC_final.docx"] = b"rascunho temporario do word"
    arquivos["Downloads/programa.exe.crdownload"] = b"download pela metade" * 50
    arquivos["Downloads/cache.tmp"] = b"temporario" * 30
    arquivos["Fotos/Thumbs.db"] = b"miniaturas do windows" * 10
    # Fase 4 (IA): 10 arquivos com conteúdo de verdade, para comparar modelos.
    # Protegidos: o organizar nunca pode mexer nestes.
    arquivos["Projetos/meu_site/package.json"] = b'{"name": "meu-site", "version": "1.0.0"}'
    arquivos["Projetos/meu_site/index.html"] = b"<html><body>Meu site</body></html>"
    arquivos["Projetos/meu_site/anotacoes.txt"] = "ideias para o site".encode()
    arquivos["Jogos/MeuJogo/jogo.exe"] = b"MZ" + bytes(200)
    arquivos["Jogos/MeuJogo/engine.dll"] = b"MZ" + bytes(100)
    arquivos["Jogos/MeuJogo/save1.sav"] = b"progresso do jogo"
    arquivos["OneDrive/relatorio_estagio.txt"] = "Relatório de estágio — sincronizado com a nuvem".encode()
    # Nomes genéricos: as regras não sabem o que são, então vão para a IA.
    arquivos["Downloads/Novo Documento.txt"] = "Reunião do grupo de TCC na quinta às 19h, levar o cronograma.".encode()
    arquivos["Downloads/scan_0001.txt"] = "Comprovante de matrícula 2026/2, curso de ADS, aluno Carlos.".encode()
    for nome, texto in AMOSTRAS_IA.items():
        arquivos[f"Amostras_IA/{nome}"] = texto.encode("utf-8")
    arquivos["Amostras_IA/contrato_aluguel.docx"] = bytes_docx_com_texto(
        "CONTRATO DE LOCAÇÃO RESIDENCIAL. Locador: João Pereira. Locatária: Ana Souza. "
        "Imóvel: Rua das Flores, 120, apto 32, Campinas-SP. Prazo de 30 meses a partir de 01/02/2026. "
        "Aluguel mensal de R$ 1.450,00 com vencimento todo dia 10, reajustado pelo IGP-M.")
    return arquivos


AMOSTRAS_IA = {
    "receita_bolo_cenoura.txt": (
        "Bolo de cenoura da vó\n\nIngredientes:\n- 3 cenouras médias\n- 4 ovos\n- 1 xícara de óleo\n"
        "- 2 xícaras de açúcar\n- 2 xícaras de farinha de trigo\n- 1 colher de fermento\n\n"
        "Modo de preparo: bata no liquidificador a cenoura, os ovos e o óleo. Misture o açúcar e a farinha, "
        "e por último o fermento. Asse por 40 minutos a 180 graus. Cobertura de chocolate opcional.\n"),
    "anotacoes_aula_redes.md": (
        "# Redes de Computadores — Aula 7 (14/10)\n\n## Modelo TCP/IP\n- Camada de aplicação: HTTP, DNS, SMTP\n"
        "- Transporte: TCP (confiável, com handshake) e UDP (sem conexão)\n- Rede: IP, roteamento\n\n"
        "## Para a prova\n- Diferença entre TCP e UDP\n- Máscara de sub-rede /24 = 255.255.255.0\n"
        "- Exercício: calcular faixa de IPs da rede 192.168.10.0/26\n"),
    "gastos_outubro.csv": (
        "data;descricao;categoria;valor\n01/10/2026;Aluguel;Moradia;1450,00\n03/10/2026;Mercado Extra;Alimentação;"
        "312,45\n05/10/2026;Conta de luz;Moradia;187,90\n08/10/2026;Uber;Transporte;23,50\n"
        "12/10/2026;Farmácia;Saúde;64,30\n15/10/2026;Internet;Moradia;99,90\n20/10/2026;Ifood;Alimentação;58,00\n"),
    "curriculo_carlos.txt": (
        "Carlos Eduardo — Currículo\nEstudante de Análise e Desenvolvimento de Sistemas (4º semestre)\n\n"
        "Objetivo: estágio em desenvolvimento de software.\n\nConhecimentos: Python, SQL, Git, HTML/CSS, "
        "noções de Java.\nProjetos: Faxineiro — organizador de arquivos com IA local (Python, SQLite, Ollama).\n"
        "Idiomas: inglês intermediário.\nContato: (19) 99999-0000\n"),
    "backup_fotos.py": (
        "import shutil\nfrom pathlib import Path\n\n# Copia as fotos do celular para o HD externo, por ano\n"
        "ORIGEM = Path('E:/DCIM/Camera')\nDESTINO = Path('F:/Backup/Fotos')\n\nfor foto in ORIGEM.glob('*.jpg'):\n"
        "    ano = foto.stat().st_mtime\n    destino = DESTINO / str(ano)\n    destino.mkdir(parents=True, exist_ok=True)\n"
        "    shutil.copy2(foto, destino)\n"),
    "email_professor.txt": (
        "Assunto: Entrega do trabalho de Banco de Dados\n\nOlá, professor Marcos,\n\nGostaria de pedir mais dois "
        "dias para entregar o trabalho de modelagem do banco de dados da clínica veterinária, porque meu "
        "notebook estragou na semana passada. Já terminei o diagrama ER e falta só a normalização.\n\n"
        "Obrigado,\nCarlos\n"),
    "lista_compras.txt": "Lista de compras do mês\n- arroz 5kg\n- feijão\n- café\n- leite (6)\n- detergente\n- papel higiênico\n- frango\n- banana\n",
    "log_erro_servidor.log": (
        "2026-10-20 14:02:11 ERROR [api] Falha ao conectar no banco de dados: timeout após 30s\n"
        "2026-10-20 14:02:11 WARN  [api] Tentando reconectar (tentativa 1 de 5)\n"
        "2026-10-20 14:02:41 ERROR [api] Falha ao conectar no banco de dados: timeout após 30s\n"
        "2026-10-20 14:03:12 INFO  [api] Conexão restabelecida com postgres://localhost:5432/loja\n"),
    "senha_wifi_casa.txt": "Rede: CasaDosSilva_5G\nSenha do roteador: troque-esta-senha\nIP do roteador: 192.168.0.1\n",
}


def bytes_docx_com_texto(texto: str) -> bytes:
    content_types = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        b'<Override PartName="/word/document.xml" ContentType="application/'
        b'vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'
    )
    corpo = f"<w:document><w:body><w:p><w:r><w:t>{texto}</w:t></w:r></w:p></w:body></w:document>"
    return bytes_zip({"[Content_Types].xml": content_types, "word/document.xml": corpo.encode("utf-8")})


PASTAS_VAZIAS = ["Projetos/antigo", "Projetos/vazio_com_sub/sub1/sub2", "Musicas"]


def main() -> int:
    criados = 0
    for relativo, dados in amostras().items():
        destino = PASTA_TESTE / relativo
        if destino.exists():
            continue
        destino.parent.mkdir(parents=True, exist_ok=True)
        with open(destino, "xb") as f:  # "x" falha se o arquivo já existir
            f.write(dados)
        criados += 1
    for relativa in PASTAS_VAZIAS:
        (PASTA_TESTE / relativa).mkdir(parents=True, exist_ok=True)
    total = sum(1 for _ in PASTA_TESTE.rglob("*") if _.is_file())
    print(f"Criados {criados} arquivos novos em {PASTA_TESTE} (total: {total}).")
    return 0


if __name__ == "__main__":
    os.chdir(RAIZ)
    sys.exit(main())
