# Fase 0 — Estudo de referência

Estudo de 5 apps de código aberto para decidir o que o Faxineiro vai ter.
Código lido em clones locais (`referencias/`, fora do Git) em 26/10/2026.
Nada foi executado: só leitura do código e das issues abertas no GitHub.

| App | Repositório | Linguagem | Licença |
|---|---|---|---|
| Local File Organizer | QiuYannnn/Local-File-Organizer | Python | MIT |
| fo-core | curdriceaurora/fo-core | Python | MIT ou Apache-2.0 |
| Czkawka | qarmin/czkawka | Rust | MIT (núcleo) / GPL (apps) |
| dupeGuru | arsenetar/dupeguru | Python + C | GPL-3.0 |
| WinDirStat | windirstat/windirstat | C++ | GPL-3.0 |

**Não estudados:**
- **LazyFiles:** não achei nenhum repositório com esse nome que seja um organizador de arquivos.
- **SlothSort:** só existem projetos minúsculos de hackathon. O mais parecido com a
  descrição é `tommy-webguru/slothsort`, que tem dry-run por padrão e desfazer em um comando.
  As ideias dele (simulação e desfazer) já aparecem no fo-core, que é bem mais completo.

---

## 1. Tabela comparativa

Legenda: ✅ tem · ⚠️ tem, com ressalva · ❌ não tem

| Funcionalidade | Local File Org. | fo-core | Czkawka | dupeGuru | WinDirStat |
|---|---|---|---|---|---|
| Organizar em pastas por conteúdo (IA) | ✅ | ✅ | ❌ | ❌ | ❌ |
| Organizar por data / tipo | ✅ | ✅ | ❌ | ❌ | ❌ |
| IA local (offline) | ✅ Nexa SDK | ✅ Ollama | ❌ | ❌ | ❌ |
| Funciona sem a IA | ⚠️ só por data/tipo | ✅ fallback por metadados | — | — | — |
| Prévia antes de agir (dry-run) | ✅ árvore simulada | ✅ `--dry-run` / `preview` | ✅ | ❌ | ❌ |
| Desfazer | ❌ | ✅ undo/redo + histórico | ❌ | ❌ | ❌ |
| Histórico de operações | ⚠️ só log em texto | ✅ SQLite | ❌ | ❌ | ❌ |
| Lixeira em vez de apagar | — (não apaga) | ✅ pasta de backup | ✅ opção | ✅ padrão (send2trash) | ✅ opção |
| Duplicados exatos | ❌ | ✅ | ✅ | ✅ | ✅ |
| Etapas do hash | — | tamanho → hash completo | tamanho → 4 KB → completo | tamanho → 16 KB → completo | tamanho → pequeno → médio → grande |
| Algoritmo de hash | — | SHA-256 / MD5 | **BLAKE3** (padrão), xxh3, crc32 | xxhash128 (ou MD5) | BCrypt (Windows) |
| Cache de hashes | ❌ | não verificado | ✅ arquivo .bin | ✅ SQLite | ❌ |
| Imagens parecidas | ❌ | ⚠️ extra opcional | ✅ | ✅ blocos 15×15 | ❌ |
| Músicas parecidas | ❌ | ❌ | ✅ tags e áudio | ✅ tags | ❌ |
| Arquivos grandes | ❌ | ✅ `analyze` | ✅ | ❌ | ✅ |
| Pastas e arquivos vazios | ❌ | ❌ | ✅ | ❌ | ⚠️ |
| Arquivos temporários / lixo | ❌ | ❌ | ✅ | ❌ | ✅ limpezas do Windows |
| Arquivos corrompidos / extensão errada | ❌ | ❌ | ✅ | ❌ | ❌ |
| Mapa visual do disco | ❌ | ❌ | ❌ | ❌ | ✅ treemap |
| Busca por conteúdo | ❌ | ✅ BM25 / vetores | ❌ | ❌ | ⚠️ só por nome |
| Etiquetas automáticas | ❌ | ✅ `autotag` | ❌ | ❌ | ❌ |
| Pastas de referência (nunca apagar) | ❌ | ❌ | ✅ | ✅ | ❌ |
| Lista de exclusão | ⚠️ ignora ocultos | ✅ | ✅ | ✅ regex | ✅ filtros |
| Interface gráfica | ❌ terminal | ❌ terminal | ✅ | ✅ Qt | ✅ |

---

## 2. Erros e limitações de cada um

### Local File Organizer
- **Instalação quebrada.** A maioria das issues abertas é sobre o Nexa SDK, que não instala
  (#68, #67, #65, #42, #36, #51). Depender de uma biblioteca pouco mantida derrubou o projeto.
- **Estoura o limite de texto da IA.** O arquivo inteiro vai no prompt e passa do limite de
  2048 tokens (#30, com 15 comentários, e #43). O código não corta o texto antes de enviar.
- **Arquivo corrompido derruba o programa** (#31). Falta tratar erro por arquivo.
- **Não tem desfazer nem histórico.** Ele cria *hard links* numa pasta nova, então os
  originais ficam intactos. Isso é seguro, mas não organiza de verdade: os arquivos continuam
  bagunçados no lugar de origem.
- **Sem interface gráfica.** Tudo é feito por perguntas no terminal (#50).
- A IA só vê o conteúdo, sem o caminho e o nome do arquivo, que ajudariam (#66).

### fo-core
- **Projeto enorme para uma pessoa:** cerca de 1.260 arquivos, ainda em beta (2.0.0-beta.7),
  com só 1 estrela. Muita coisa ainda não foi testada por usuários reais.
- **Duplicados sem hash parcial.** Agrupa por tamanho e já calcula o hash completo em SHA-256.
  Em arquivos grandes de mesmo tamanho, isso é lento.
- **Proteções mais fracas no Windows.** As defesas extras contra troca de arquivo durante a
  operação usam recursos de Linux/macOS. No Windows o código cai num `unlink` simples
  (`deduplication/backup.py`).
- Bom exemplo de **mover com segurança**: grava um diário (journal) antes de mover entre discos
  e, se o programa travar no meio, termina ou desfaz a operação na próxima vez que abrir
  (`undo/durable_move.py`).

### Czkawka
- **Não organiza nada**, só encontra problemas. Também não tem desfazer: se você apagar sem
  usar a lixeira, não há volta.
- **Duplicados que escapam:** relatos de duplicados não detectados (#944, #1699) e um caso
  alegado de falso positivo com BLAKE3 (#1976).
- **Não encontra pastas duplicadas inteiras** (#1182, #976, #676) nem procura dentro de
  arquivos .zip (#616).
- **Não dá para pausar e retomar** uma varredura longa (#892, #157).
- **Sites falsos com vírus** se passando pelo projeto (#1583). Para o Faxineiro, isso reforça
  que ele não deve se atualizar sozinho por links da internet.

### dupeGuru
- **Lento com muitos arquivos.** Compara os arquivos de dois em dois dentro de cada grupo de
  mesmo tamanho (`itertools.combinations` em `core/engine.py`). A etapa "Almost done!
  Fiddling with results..." pode levar horas ou nunca terminar (#571, com 42 comentários;
  #273 e #962).
- **Risco de falso positivo em arquivos grandes:** com a opção de "amostras" ligada, compara só
  3 pedaços de 1 MB (início, meio e fim) em vez do arquivo inteiro.
- **Pastas que começam com ponto são sempre ignoradas**, sem aviso (#536).
- **Duplicados que escapam** (#756, #1204) e falso positivo com .eml (#1279).
- Imagens HEIC e WebP não são suportadas no modo de fotos (#455, #1141).
- Não tem linha de comando (#288) e está pouco mantido (564 issues abertas).

### WinDirStat
- **Apagar de vez existe e é fácil.** Tem as opções "para a lixeira" e "apagar
  permanentemente", e o aviso de confirmação tem uma caixa "não mostrar de novo".
- **Também tem amostragem:** acima de 64 MB, o hash pode ser feito por amostras
  (`m_sampleLargeFiles`), com o mesmo risco de falso positivo do dupeGuru.
- **A interface trava** com muitos resultados (#743) e não dá para cancelar depois de apagar
  muitos arquivos (#663).
- **Não compara com uma varredura anterior** para mostrar o que cresceu (#104).
- Só funciona no Windows e não usa IA. Mesmo assim, é a referência de mapa visual.

---

## 3. O que o Faxineiro vai ter

O melhor de cada um, com o erro corrigido e ligado às regras do `CLAUDE.md`.

### Segurança (a base de tudo)
1. **Quarentena em vez de apagar** (do dupeGuru e do Czkawka, mas sem a opção de apagar de vez).
   "Excluir" move para `_quarentena`, sempre. *Corrige:* o WinDirStat e o Czkawka deixam apagar
   permanentemente.
2. **Prévia obrigatória (dry-run)** antes de qualquer movimento (do Local File Organizer e do
   fo-core). A confirmação aparece sempre, sem opção "não mostrar de novo".
   *Corrige:* o aviso do WinDirStat que pode ser desligado.
3. **Histórico com desfazer**, guardado no SQLite (do fo-core): cada operação registra origem,
   destino, data e hash.
4. **Mover com diário:** primeiro registra a intenção, depois move, depois marca como feito.
   Se o programa travar, termina ou desfaz ao abrir (ideia do `durable_move` do fo-core,
   escrita do zero e mais simples).
5. **Lista de bloqueio configurável:** `C:\Windows`, `C:\Program Files`, `C:\ProgramData`,
   `AppData` e pastas de programas vêm bloqueadas por padrão.
6. **Pastas de referência**, que nunca têm arquivos marcados para sair (do Czkawka e do dupeGuru).

### Duplicados
7. **Três etapas com BLAKE3** (como o Czkawka): tamanho → hash parcial → hash completo.
   *Corrige:* nunca decide só por amostras, como dupeGuru e WinDirStat podem fazer. Para marcar
   como duplicado, o hash completo tem que bater.
8. **Comparar por dicionário de hash, não de dois em dois.** Os arquivos são agrupados pelo hash
   numa passada só. *Corrige:* a lentidão do dupeGuru (#571).
9. **Cache no índice SQLite:** se tamanho e data de modificação não mudaram, o hash é
   reaproveitado (do Czkawka e do dupeGuru).
10. **Mostrar por que dois arquivos foram considerados iguais** (tamanho e hash), para o
    usuário confiar. *Corrige:* as reclamações de falso positivo.
11. Depois: imagens parecidas, com ideia do dupeGuru (blocos) ou hash perceptual. Pastas
    duplicadas inteiras, pedido antigo no Czkawka (#1182).

### Lixo e espaço
12. **Arquivos grandes, pastas vazias, arquivos vazios e temporários** (do Czkawka).
13. **Mapa visual do disco** tipo treemap (do WinDirStat), lendo do índice, sem varrer de novo.
14. **Comparar com a varredura anterior** para mostrar o que cresceu. *Corrige:* o pedido
    #104 do WinDirStat, fácil para nós porque já guardamos o índice.

### IA local
15. **Ollama local com modelo leve** (`qwen2.5:3b`). *Corrige:* o Nexa SDK do Local File
    Organizer, que não instala.
16. **Cortar o texto antes de mandar para a IA** (por exemplo, os primeiros milhares de
    caracteres) e incluir o nome e a pasta do arquivo no prompt. *Corrige:* o estouro de
    contexto (#30) e o pedido #66.
17. **Modo sem IA:** se o Ollama estiver desligado, classifica por extensão, data e metadados
    e marca como "revisar" (como o fallback do fo-core).
18. **Um erro por arquivo não para tudo:** arquivo corrompido vira um aviso na lista.
    *Corrige:* o travamento #31 do Local File Organizer.
19. **Descrição e etiquetas guardadas no índice** (do autotag do fo-core), sem copiar o arquivo.

### Uso no dia a dia
20. **Interface gráfica em PySide6**, com a varredura numa thread separada, barra de
    progresso e botões de pausar e cancelar. *Corrige:* a falta de interface (Local File
    Organizer, fo-core), a tela travando (WinDirStat #743) e a falta de pausa (Czkawka #892).
21. **Mostrar o que foi ignorado e por quê** (pasta oculta, sem permissão, bloqueada).
    *Corrige:* o dupeGuru, que ignora pastas com ponto sem avisar (#536).
22. **Internet desligada por padrão.** Só pesquisa o *nome ou tipo* de um arquivo desconhecido
    quando o usuário ativar, nunca o conteúdo.

### Fora do escopo por enquanto
- Busca semântica com vetores, copiloto em linguagem natural, vigiar pastas em segundo plano
  (fo-core). Muito peso para a primeira versão.
- Recuperar arquivos apagados e limpezas do sistema (WinDirStat). Mexe em áreas que a regra 3
  proíbe.

---

## 4. Licenças
- **MIT / Apache** (Local File Organizer, fo-core, núcleo do Czkawka): dá para copiar código
  mantendo o aviso de licença.
- **GPL-3.0** (dupeGuru, WinDirStat, apps do Czkawka): para uso pessoal, sem distribuir, não há
  obrigação. Se o Faxineiro for publicado com código copiado deles, ele também teria que ser GPL.
- **Decisão:** o Faxineiro nasce do zero. Os apps foram usados como estudo de ideias, não como
  base de código, então nenhuma licença restringe o projeto.
