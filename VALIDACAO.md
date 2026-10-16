# Validação da v3.0.0

Linux, Python 3.12, Node e Chromium. Data: 16/10/2026.

- 201 testes Python e 17 subtestes aprovados, incluindo ciclos personalizados e atributos dos itens recebidos.
- Verificação sintática dos scripts JavaScript e teste Node de ícones aprovados.
- Quatro fluxos de navegador com API simulada: catálogo/criação/agendamento; notificações/ofertas; chat/Counter Offer; navegação e preferências da interface Sonaria.
- Validados indicadores, filtro de disponibilidade, persistência de galeria/lista, atalhos fora de campos de edição, menu móvel, fonte local, movimento reduzido e ausência de rolagem horizontal em 320, 390, 650, 768, 1024 e 1440 px.
- Mantidos testes de preço fixo/ofertas, fila, iniciar/parar, relógios, aceitação/recusa, erro de oferta desatualizada, chat automático e preservação de rascunho/rolagem.
- Capturas revisadas de painel, catálogo, agendamentos, notificações e chat; os dados usados nas capturas são fictícios de teste.
- ZIP verificado por CRC e comparação com os arquivos de origem; testes Python executados também no pacote extraído. Fonte e licença incluídas.

O redesign não altera os contratos de escrita externa. Os testes de navegador usam respostas simuladas; envios reais não foram revalidados. O bloqueio HTTP 403 documentado na v2.3.0 permanece uma limitação conhecida da validação externa.

O iniciador Windows não foi executado neste ambiente Linux. O ZIP exclui credenciais, configurações locais e ambiente virtual.
