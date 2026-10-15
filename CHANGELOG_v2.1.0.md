# v2.1.0 — Studio e agendamentos

- Nova interface em preto neutro e azul: destaque inicial, órbita animada, transições, cartões e layout responsivo. Suporte a movimento reduzido e teclado.
- Modos Pedir ofertas e Somente preço fixo em Shooms, com validação e contrato de criação fornecido pelo usuário.
- Aba Agendamentos no topo de Anúncios, seleção de itens pelo catálogo e fila com modelos independentes.
- Publicação inicial imediata, com pelo menos 60 segundos entre envios; renovação padrão após uma hora por item, excluindo antes de recriar.
- Quantidade, características e preço preservados em todos os ciclos; pausa individual e interrupção da fila inteira.
- Estado persistido, reinício pausado, proteção contra concorrência e tratamento de escritas incertas, autenticação e limites HTTP.
- Verificação de disponibilidade a cada 10 segundos, antecipada para horários conhecidos; republicação no mesmo ciclo da detecção.
- Removido o controle de intervalo de tentativas sem sinal. A automação normal ignora anúncios com agendamento ativo.

Consulte VALIDACAO.md para os testes executados e os limites de validação real.
