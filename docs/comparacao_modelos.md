# Comparação de modelos (mesmos 10 arquivos, mesmo prompt do app)

| Modelo | 1ª resposta (carrega o modelo) | Média das outras 9 | Total | RAM disponível antes → mínima → depois |
|---|---|---|---|---|
| qwen2.5:0.5b | 10.0 s | 2.9 s | 36 s | 517 MB → 139 MB → 705 MB |
| qwen2.5:1.5b | 11.5 s | 3.8 s | 46 s | 705 MB → 6 MB → 1645 MB |

## Descrições lado a lado

| Arquivo | qwen2.5:0.5b | qwen2.5:1.5b |
|---|---|---|
| anotacoes_aula_redes.md | arquivo de aula de computador pessoal, texto, 341 B, 2026, 2026, 192.168.10.0/26, 255.255.255.0, 255.255.255.0, 2 *(10 s)* | Anotações da aula sobre redes de computadores. *(11 s)* |
| backup_fotos.py | O arquivo backup_fotos.py é um arquivo de backup de imagens de IA, armazenado em uma pasta chamada "Amostras_IA". Ele tem um tamanho de 339 bytes e foi modificado em 2026. *(4 s)* | Backup de fotos para IA experimentos. *(2 s)* |
| contrato_aluguel.docx | Arquivo de contrato de locação residencial. *(2 s)* | Contrato de aluguel residencial. *(4 s)* |
| curriculo_carlos.txt | Arquivo de currículo de estagiário de desenvolvimento de software. *(3 s)* | Curriculo de um estudante de Análise e Desenvolvimento de Sistemas. *(5 s)* |
| email_professor.txt | Arquivo de notas pessoais sobre a entrega de trabalho de bancos de dados. *(2 s)* | Arquivo de email de entrega de trabalho de banco de dados. *(4 s)* |
| gastos_outubro.csv | Arquivo com gastos de outubro 2026. *(4 s)* | Arquivo contendo gastos mensais de uma pessoa. *(5 s)* |
| lista_compras.txt | Arquivo lista_compras.txt contém lista de compras para o mês, contendo itens como arroz, feijão, café, leite, detergente, papel higiênico e frango. *(4 s)* | Lista de compras do mês. *(2 s)* |
| log_erro_servidor.log | Arquivo de logs de conexão com o banco de dados PostgreSQL. *(3 s)* | Arquivo de log de erro do servidor, texto, tamanho pequeno, modificado em out/2026. *(6 s)* |
| receita_bolo_cenoura.txt | Arquivo de receitas de bolo de cenoura da vó. *(3 s)* | Receita de bolo de cenoura da vó. *(4 s)* |
| senha_wifi_casa.txt | Arquivo de configuração Wi-Fi do computador pessoal. *(2 s)* | Arquivo de texto contendo a senha WiFi da casa. *(3 s)* |
