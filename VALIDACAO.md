# Validação da v2.3.0

Ambiente Linux, Python 3.12, Node e Chromium. Data: 15/10/2026.

- 187 testes Python e 17 subtestes aprovados.
- Teste Node de ícones aprovado.
- Navegador: chat com atualização automática, ordem cronológica, rascunho e rolagem preservados, falhas de envio/leitura, confirmação/cancelamento da contraproposta, revisão de valores e layout em celular.
- Navegador: central de notificações, aceitação/recusa, oferta desatualizada, marcação como lida, ícones locais, teclado e celular.
- Navegador: catálogo, preço fixo/ofertas, fila, iniciar/parar, contadores, categorias e movimento reduzido.
- Contratos de contraproposta testados com e sem oferta raiz, estoque, valores inválidos, ação repetida, resposta de erro e revisão alterada.
- Chat testado com o objeto de conversa no envio, confirmação por `messageId`, isolamento de conta, verificação de participantes e continuidade depois de fechar a oferta.

Os testes de navegador simulam a API. O código público do Traderie respondeu HTTP 200 e confirmou os contratos; consultas autenticadas de ofertas e conversas responderam HTTP 403. Não foi possível validar envios reais com o token. Os resultados simulados não comprovam aceitação pelo serviço externo.

O iniciador Windows não foi executado neste ambiente Linux. O ZIP não contém credenciais, configuração local ou ambiente virtual.
