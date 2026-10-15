# Validação da v2.0.0

Ambiente de desenvolvimento: Linux, Python 3.12, Node 24 e Chromium. Data: 15/10/2026.

- 114 testes Python e 17 subtestes aprovados.
- Teste de ícones, traits e URLs no Node aprovado.
- Teste de navegador com API simulada aprovado: desktop/celular, seleção, payload de publicação, filtros de categoria, recuperação de falhas, relógio ao vivo e teclado.
- Catálogo oficial consultado ao vivo: espécies, plushies, paletas, pesquisa por nome e paginação de 24 para 48 itens.
- Formulário real de Mijusuima validado sem publicar: tipo `Creatures`, propriedade espécie/slot `828` e mutação Glow Tail `135`.
- Dependências instaladas a partir dos arquivos fixados; `pip check` sem inconsistências.
- API Flask local e interface responderam HTTP 200.

Publicações e republicações reais não foram executadas. A consulta pública dos anúncios da conta de teste retornou uma lista vazia. O token não foi incluído no pacote. O iniciador Windows foi preparado, mas não executado em Windows neste ambiente Linux.

Para reproduzir os testes e entender as limitações de disponibilidade, consulte README.md e TRADERIE_RESEARCH.md.
