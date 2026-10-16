# Validação da v2.4.0

Linux, Python 3.12, Node e Chromium. Data: 16/10/2026.

- 201 testes Python e 17 subtestes aprovados.
- Intervalos livres de 1, 7, 37, 91, 2880 e 525600 minutos geram o próximo ciclo correto; valores inválidos são rejeitados antes de salvar.
- Itens recebidos preservam atributos próprios, imagens, variantes e grupos. Características do anúncio do vendedor e definições do catálogo não são copiadas para a oferta.
- Mudanças nas características alteram a revisão usada na confirmação da oferta.
- Teste Node de ícones aprovado.
- Chromium: salvamento com intervalo digitado de 37 minutos; Keruku recebido como Slot com Health, Stamina Regen e Corrupt; recuperação da imagem no catálogo; layout em celular.
- Chromium: regressões de catálogo, criação, fila, notificações, aceitação/recusa, chat e Counter Offer aprovadas.

Os testes usam respostas simuladas. O bloqueio HTTP 403 registrado na v2.3.0 não foi reavaliado nesta revisão; não houve novas escritas reais no Traderie. O iniciador Windows não foi executado neste ambiente Linux.

O ZIP exclui credenciais, configurações locais e ambiente virtual. O pacote extraído também foi testado.
