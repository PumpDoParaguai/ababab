# v2.2.0 — Painel pessoal e notificações

- Removido o banner promocional; navegação e ferramentas ficam no topo.
- Rótulos de propriedades exibem somente Espécie ou Slot, preservando o contrato da API.
- Ícones da API são prioritários; novos ícones locais de reserva para Corrupt e outras propriedades evitam depender exclusivamente do CDN.
- Central de notificações e ofertas, com consultas automáticas a cada 15 segundos, deduplicação de avisos e marcação como lida.
- Conteúdo de ofertas novamente visível: valores, itens, grupos, quantidade, comprador e avaliações quando informados.
- Aceitar/recusar com confirmação, verificação de conta, trava contra cliques simultâneos e validação da versão revisada da oferta.
- Aceitar não abre conversa nem envia mensagens automaticamente; o chat continua acessível pelo botão Mensagem.
- Falhas preservam a última informação com aviso; autenticação e limites de requisições têm pausa apropriada.

Pendente: contraproposta nativa dentro do painel. O botão Counter Offer no Traderie abre o anúncio no site oficial enquanto não houver URL, método e payload confirmados para essa ação. A conexão externa deste ambiente foi bloqueada pelo proxy; não houve validação de escritas ao vivo nesta revisão.
