# Traderie CoS Assistant — v2.2.0

Painel local para anúncios de Creatures of Sonaria. Interface em português, preto neutro e azul. Projeto independente, não afiliado ao Traderie. GPL-3.0-or-later; derivado de `ImanolBarba/traderie-bot`.

## Iniciar no Windows

**[Baixar Traderie CoS Assistant v2.2.0 (ZIP)](https://github.com/PumpDoParaguai/ababab/raw/refs/heads/main/downloads/Traderie_CoS_Assistant_v2.2.0.zip)**

1. Extraia o ZIP em uma pasta nova.
2. Instale Python 3.10 ou superior e execute `INICIAR_WINDOWS.bat`.
3. Abra o painel local na porta 8765. O iniciador abre o navegador automaticamente.
4. Explore **Novo anúncio** para escolher um item do catálogo. Conecte sua conta para publicar ou republicar.

No Linux/macOS:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python app.py
```

O servidor escuta exclusivamente em `127.0.0.1:8765`. Deixe o processo aberto para usar a automação. Processos em execução não sobrevivem ao encerramento ou à restauração de um ambiente na nuvem.

## Novo anúncio

- Catálogo do Traderie separado por espécie, slot, plushie e paleta; funciona sem anúncios anteriores e sem conectar uma conta.
- Pesquisa por nome, seleção por teclado ou clique, resumo do item e quantidade.
- IDs de itens permanecem internos. Escolha **Pedir ofertas** ou **Somente preço fixo**, informando o valor em Shooms. Não há médias de mercado nem cotações automáticas.
- Características de slots vêm das opções do catálogo. As opções, tipos e identificadores vêm do item selecionado. Mutações e traits são caixas de seleção com os limites de grupo informados pelo catálogo. O identificador de espécie/slot também é obtido dinamicamente.
- Falhas de acesso são exibidas com **Tentar novamente**. Um catálogo bloqueado não é apresentado como uma busca bem-sucedida sem resultados.

O catálogo usa diretamente a API oficial `/api/creaturesofsonaria/items`, verificada com consultas reais. Carrega 24 itens por página, com botão **Carregar mais itens**, pesquisa por nome e filtro de categoria. Nomes, imagens, tipos e propriedades são preservados; dados de preços retornados pela API são descartados. Nenhuma consulta de catálogo depende dos anúncios da conta.

## Republicação e relógios

Na aba **Meus anúncios**, ative **Republicação automática** e clique em **Aplicar**. O primeiro ciclo começa imediatamente. Em seguida:

- O programa consulta a disponibilidade a cada 10 segundos. Se o servidor informar uma liberação antes disso, a próxima consulta é antecipada para esse horário.
- Flags e horários explícitos da API têm prioridade. Uma resposta de bloqueio continua prevalecendo.
- Quando esses campos estão ausentes, aplica as mesmas regras do botão Relist verificadas no site em 15/10/2026: **20 horas** normalmente; **18 horas** para contas com 1.000 ou mais avaliações; **6 horas** ou **30 minutos** quando os papéis da conta conferem esses benefícios. O perfil é consultado e mantido em cache por até 5 minutos.
- Sem acesso ao perfil e sem sinal explícito, a disponibilidade permanece desconhecida. O programa não afirma que pode republicar.
- Um horário calculado indica quando tentar; o sucesso depende da aceitação da API. As regras do serviço podem mudar em versões futuras.
- Republicações manuais e automáticas compartilham trava e proteção contra repetição da mesma atualização aceita. Ao detectar disponibilidade, o worker envia a republicação no mesmo ciclo, sem intervalo adicional de “tentativas sem sinal”. Anúncios de agendamentos ativos ficam fora dessa automação para não misturar os dois ciclos.
- Limites HTTP 429 interrompem o lote e respeitam `Retry-After`. Erros de autenticação ou anti-bot pausam a automação.

O tempo desde a atualização de cada anúncio avança a cada segundo no navegador, inclusive para anúncios antigos. O painel sincroniza com o servidor local a cada 10 segundos, reutilizando dados obtidos nos últimos 30 segundos (a automação atualiza a cópia a cada 10 segundos). O horário mostrado só muda com informação recebida do Traderie; não é inventado após uma tentativa.

A detecção sem horário conhecido pode levar até o próximo ciclo, além do tempo de rede. Não há uma conexão de eventos em tempo real do Traderie confirmada neste projeto.

## Agendamentos automáticos

Em **Anúncios → Agendamentos**, clique em **Adicionar item** e selecione itens do catálogo. Cada item mantém sua quantidade, características e modo de venda, incluindo preço fixo. Escolha o intervalo (padrão: **1 hora**), salve a fila e clique em **Iniciar fila**.

- O primeiro anúncio é enviado imediatamente pelo worker (até 0,5 s, mais rede). Os demais respeitam pelo menos **60 segundos entre publicações**, inclusive após atrasos ou ao adicionar mais itens.
- Uma hora após a publicação de cada item, seu anúncio gerenciado é **excluído e depois recriado** com o mesmo modelo. Exemplo: A às 12h, B às 12h01; A volta a partir das 13h e B a partir das 13h01. O horário efetivo depende da rede e da fila.
- A fila segue até você pausar um item ou clicar em **Interromper tudo**. O anúncio atual é preservado ao interromper; uma requisição já enviada pode terminar.
- Excluir o anúncio remove também suas negociações. Somente os IDs criados pelo próprio agendamento são excluídos. Se um anúncio gerenciado já foi removido no site, o agendamento cria o próximo no ciclo previsto.
- O contador avança a cada segundo e a tela consulta o estado da fila a cada 3 segundos. A opção **Ver configurações** mostra os atributos preservados.
- Falhas de escrita pausam o item para revisão, sem repetir automaticamente uma criação incerta. Falha de autenticação/anti-bot pausa a fila; HTTP 429 adia os próximos envios conforme `Retry-After`.
- Até 20 itens por conta; intervalos de 15 minutos a 24 horas. Se houver mais itens vencidos que a capacidade de um por minuto, eles aguardam a vez sem envios simultâneos.
- As configurações e IDs são salvos localmente. Ao reiniciar ou reconectar, os agendamentos voltam **pausados**. Retomar respeita o tempo desde a última publicação. Deixe o programa aberto e o computador acordado para executar os ciclos.

## Interface e outros recursos

Visual compacto para uso pessoal, em preto neutro e azul, sem banner promocional. Mantém animações de entrada, destaque ao passar o mouse, indicadores pulsantes e transições. A preferência do sistema por movimento reduzido desativa as animações. A interface se adapta ao celular e as abas podem ser navegadas por teclado.

A navegação principal tem **Anúncios** e **Usuário**, com abas **Meus anúncios** e **Agendamentos** no topo da área de anúncios. Ofertas e conversas ficam no contexto de cada anúncio. Agrupamento, exclusão com confirmação e sons opcionais permanecem disponíveis.

## Notificações e ofertas

O botão **Notificações**, no topo de Anúncios, abre a central da conta conectada. O servidor consulta notificações e ofertas abertas a cada 15 segundos enquanto o programa está aberto; o navegador recebe a atualização automaticamente, sem recarregar a página. Não há webhook ou conexão de eventos confirmados do Traderie.

- Exibe as 50 notificações mais recentes e as ofertas abertas retornadas pelo serviço, com valores em Shooms, itens, grupos alternativos e quantidade solicitada, quando presentes na resposta.
- Notifica novas atividades no painel, sem repetir avisos para o mesmo ID e sem avisar por todo o histórico ao conectar.
- **Aceitar** e **Recusar** exigem confirmação. O servidor relê a oferta, confere a conta e compara os valores com a versão revisada; ofertas alteradas precisam ser revisadas novamente. Aceitar não envia uma mensagem automática.
- **Mensagem** abre o chat existente. As notificações selecionadas podem ser marcadas como lidas no Traderie.
- **Counter Offer no Traderie** abre o anúncio no site oficial. **A contraproposta nativa dentro do painel ainda está pendente**: falta confirmar URL, método e payload dessa ação. Não enviamos uma mensagem de chat fingindo ser contraproposta formal.
- Falhas mantêm os últimos dados com aviso de sincronização; autenticação/anti-bot pausa as consultas e HTTP 429 respeita `Retry-After`. Reconectar limpa o estado da conta anterior.

## Ícones e rótulos

Os cards exibem apenas **Espécie** ou **Slot**, sem a pergunta do catálogo. A URL de ícone informada pela API tem prioridade sobre nomes de arquivo estimados. Em falhas do CDN, o pacote usa ícones locais de reserva, incluindo um símbolo próprio para Corrupt. Os ícones de reserva são ilustrações do painel, não cópias dos arquivos oficiais. O formato interno dos atributos enviado ao Traderie permanece intacto.

## Credenciais e rede

O token de sessão é recebido no formulário local ou por `TRADERIE_AUTH` e permanece na memória do processo. Não está incluído no código, no ZIP ou na configuração salva. A variável de ambiente é usada na reconexão de uma conta previamente configurada. A automação começa desativada após reiniciar.

Para acesso na nuvem, permita `traderie.com` e `cdn.nookazon.com` nas configurações de rede. Isso não elimina bloqueios impostos pelo próprio site. CAPTCHA e Cloudflare não são contornados.

**Validação desta versão:** 167 testes Python e 17 subtestes, testes JavaScript e testes de navegador cobrem ofertas, notificações, ações com valores revisados, ícones de reserva, preço fixo e agendamentos. O formato de preço fixo usa o payload real fornecido pelo usuário: `currencyGroupPrices: [{group: 0, nmt: valor, currency: true}]`, `acceptListingPrice: true` e `makeOffer: false`. Nesta revisão, o proxy do ambiente retornou 403 antes de alcançar o Traderie; escritas reais não foram executadas. As leituras de catálogo documentadas em TRADERIE_RESEARCH.md pertencem à validação anterior.

A integração de contraproposta nativa ainda aguarda o contrato da requisição. O token fornecido não foi incorporado ao pacote. Imagens podem ser recusadas pelo CDN; nesse caso o painel mostra um marcador.

## Desenvolvimento e testes

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
node tests/test_property_icons.cjs
```

Com `app.py` aberto, execute o teste de navegador (requer Chromium):

```bash
CHROMIUM_PATH=/usr/bin/chromium .venv/bin/python tests/browser_smoke.py /tmp/traderie-browser
```

Para testar a central com respostas simuladas, execute `.venv/bin/python tests/browser_inbox.py /tmp/traderie-inbox`.

Para verificar somente leituras do catálogo real, execute `tests/live_catalog_smoke.py` da mesma forma, com o painel aberto.

O teste `browser_smoke.py` intercepta as respostas da API no navegador; ele valida seleção, payload de criação, categorias, recuperação de erros, relógios, teclado e telas de desktop/celular sem publicar anúncios reais. As imagens geradas são exemplos com dados simulados.

Arquivos principais: `app.py` (servidor e automação), `traderie.py` (cliente HTTP), `static/` (interface) e `tests/` (regressões).
