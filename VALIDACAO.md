# Validação da v2.1.0

Ambiente: Linux, Python 3.12, Node e Chromium. Data: 15/10/2026.

- 148 testes Python e 17 subtestes aprovados.
- Fila validada com relógio controlado: publicação inicial, separação mínima de 60 segundos, repetição a cada hora, exclusão antes da criação e modelos idênticos entre ciclos.
- Casos de atraso, pausa durante leitura/exclusão/criação, retomada, reinício, concorrência de remoção, limitação HTTP e falhas de escrita cobertos.
- Preço fixo validado contra o payload fornecido pelo usuário, incluindo a chave `currencyGroupPrices` e valores inválidos; preço preservado em ciclos sucessivos.
- Teste Node de ícones e URLs aprovado.
- Teste Chromium com APIs simuladas: oferta/preço fixo, validação do formulário, fila pelo catálogo, propriedades preservadas, iniciar/interromper, contadores, categorias, recuperação de erros, teclado e layouts desktop/celular. Animações e preferência de movimento reduzido conferidas.
- `pip check` sem inconsistências. A interface e `/api/state` respondem HTTP 200 localmente.

Nesta revisão, o proxy retornou HTTP 403 ao tentar conectar ao Traderie. Nenhuma criação, exclusão ou republicação real foi executada, embora o usuário tenha autorizado testes na conta. O payload de preço fixo foi fornecido diretamente pelo usuário a partir do site. Os testes não garantem a aceitação de futuras escritas pelo serviço.

As consultas reais de catálogo registradas em TRADERIE_RESEARCH.md pertencem à v2.0.0. O iniciador Windows não foi executado neste ambiente Linux. O ZIP não contém credenciais, configuração local ou ambiente virtual.
