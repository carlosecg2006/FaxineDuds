# Faxineiro — organizador pessoal de arquivos com IA

## O que é
App desktop pessoal (Windows) que indexa os arquivos do PC, entende o que
cada um é com IA local (Ollama, offline), acha duplicados, arquivos pesados
e lixo, sugere organização e limpa — sempre com aprovação do usuário.

## Quem usa
Carlos, estudante de ADS. Explique decisões em português simples,
um conceito por vez, sem enrolação.

## Regras invioláveis
1. Nunca apagar arquivo do usuário. "Excluir" = mover para a quarentena
   (pasta _quarentena) e registrar no histórico, com desfazer.
2. Nada é movido sem prévia (dry-run) e confirmação do usuário.
3. Nunca tocar em C:\Windows, C:\Program Files, C:\ProgramData,
   AppData e pastas de programas. Lista de bloqueio configurável.
4. O app não copia arquivos: guarda só um índice (SQLite) com caminho,
   tamanho, datas, hash, tipo e descrição da IA.
5. Durante o desenvolvimento, testar SÓ em ./pasta_teste.
6. Internet só quando o usuário ativar, e só para pesquisar o que
   um arquivo desconhecido é (nunca enviar o conteúdo do arquivo).

## Regras para o Claude (desenvolvimento)
As regras de bloqueio em `.claude/settings.json` só comparam o texto do
comando, então dá para contorná-las. Estas regras valem mesmo quando o
bloqueio não pegaria:
- Não apagar arquivos por nenhum caminho alternativo: nada de
  `python -c "os.remove(...)"`, `shutil.rmtree`, `git clean`,
  `git reset --hard` ou scripts feitos só para apagar.
- Código do app que move ou apaga arquivos só pode rodar com a pasta-alvo
  dentro de `./pasta_teste`. Os testes (pytest) devem usar pastas
  temporárias (`tmp_path`) ou `./pasta_teste`, nunca outras pastas do PC.
- Nunca dar `git push` nem mexer em configurações do Git sem pedir.
- Se um comando for bloqueado, parar e avisar o Carlos. Não procurar
  outro jeito de fazer a mesma coisa.

## Ambiente
- Windows 11, PowerShell como shell principal.
- Projeto em `D:\FaxineDuds`, versionado com Git (local, sem remoto).
- Ollama instalado com o modelo `qwen2.5:3b`.

## Tecnologia
- Python 3.11+, interface PySide6 (Qt)
- SQLite para o índice
- Hash BLAKE3 para duplicados (tamanho → hash parcial → hash completo)
- Ollama local (modelo de texto leve; modelo de visão opcional)
- Testes com pytest; commit no Git ao fim de cada fase

## Como trabalhar
- Antes de cada fase: planejar e mostrar o plano.
- Ao fim de cada fase: rodar testes, mostrar resumo curto, fazer commit.
- Atualizar a seção "Estado atual" abaixo.

## Estado atual
Fase 0 — concluída (26/10/2026). Estudo em `docs/estudo.md`; clones de
referência em `referencias/` (fora do Git, só leitura). Próxima: Fase 1.
