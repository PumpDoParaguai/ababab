# v1.13.0 — mudanças verificadas

- Página Negociações removida; interação por card de anúncio preservada.
- Removido o display de ID técnico, de NYP, de médias, community values e de controles de preço no novo anúncio.
- Editor usa somente resultados do catálogo público, sem buscar histórico de anúncios próprios.
- Cronômetro de atualização recalculado no cliente a cada segundo; lista sincroniza silenciosamente a cada minuto.
- Polling automático de disponibilidade reduzido para ~45 segundos com a aplicação rodando, sem afirmar disponibilidade quando a API não expõe um sinal.
- Bloqueio de repetição de republicações aceitas com o mesmo timestamp retornado pela API.
- Tema de superfícies negras e acentos azuis elétricos; opção de som preservada.
- Teste visual da pesquisa, do relógio e da ausência de campos de valores/IDs; testes de regressão no cliente.
