# Validação da v2.2.0

Ambiente Linux, Python 3.12, Node e Chromium. Data: 15/10/2026.

- 167 testes Python e 17 subtestes aprovados.
- Teste Node de ícones aprovado: prioridade da URL da API, Corrupt com reserva local, rótulos simplificados e preservação dos outros atributos.
- Teste de navegador da central aprovado: atualização automática sem recarregar, valores de ofertas, confirmar aceitação/recusa, erro de oferta desatualizada, marcação como lida, ícones com CDN indisponível, teclado e celular.
- Teste de navegador dos fluxos anteriores aprovado: preço fixo/ofertas, catálogo, fila, iniciar/parar, contadores, categorias, movimento reduzido e desktop/celular.
- Testes de sincronização cobrem cache, falha parcial, isolamento de conta, autenticação, Retry-After e proteção contra ações repetidas ou sobre valores modificados.

Os testes de navegador simulam a API; não alteram anúncios reais. O proxy continua recusando conexão com o Traderie, portanto não houve testes reais de aceitação/recusa/notificações nesta revisão. As leituras reais registradas em TRADERIE_RESEARCH.md pertencem à v2.0.0.

A contraproposta nativa permanece pendente de URL, método e payload. A interface oferece um link explícito ao Traderie, sem simular essa ação por mensagem. Ícones locais de reserva são desenhos do painel; arquivos oficiais inacessíveis não foram identificados como verificados.

O iniciador Windows não foi executado neste ambiente Linux. O ZIP não contém credenciais, configuração local ou ambiente virtual.
