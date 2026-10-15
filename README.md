# Traderie CoS Assistant — v2.0.0

Painel local para anúncios de Creatures of Sonaria. Interface em português, preto neutro e azul. Projeto independente, não afiliado ao Traderie. GPL-3.0-or-later; derivado de `ImanolBarba/traderie-bot`.

## Iniciar no Windows

**[Baixar Traderie CoS Assistant v2.0.0 (ZIP)](https://github.com/PumpDoParaguai/ababab/raw/refs/heads/main/downloads/Traderie_CoS_Assistant_v2.0.0.zip)**

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
- IDs de itens permanecem internos; não há campos de preço, médias ou cotações. Os anúncios são criados no modo **receber ofertas**.
- Características de slots vêm das opções do catálogo. As opções, tipos e identificadores vêm do item selecionado. Mutações e traits são caixas de seleção com os limites de grupo informados pelo catálogo. O identificador de espécie/slot também é obtido dinamicamente.
- Falhas de acesso são exibidas com **Tentar novamente**. Um catálogo bloqueado não é apresentado como uma busca bem-sucedida sem resultados.

O catálogo usa diretamente a API oficial `/api/creaturesofsonaria/items`, verificada com consultas reais. Carrega 24 itens por página, com botão **Carregar mais itens**, pesquisa por nome e filtro de categoria. Nomes, imagens, tipos e propriedades são preservados; dados de preços retornados pela API são descartados. Nenhuma consulta de catálogo depende dos anúncios da conta.

## Republicação e relógios

Ative **Republicação automática** e clique em **Aplicar**. O primeiro ciclo começa imediatamente. Em seguida:

- O programa consulta a disponibilidade a cada 30 segundos. Se o servidor informar uma liberação antes disso, a próxima consulta é antecipada para esse horário.
- Flags e horários explícitos da API têm prioridade. Uma resposta de bloqueio continua prevalecendo.
- Quando esses campos estão ausentes, aplica as mesmas regras do botão Relist verificadas no site em 15/10/2026: **20 horas** normalmente; **18 horas** para contas com 1.000 ou mais avaliações; **6 horas** ou **30 minutos** quando os papéis da conta conferem esses benefícios. O perfil é consultado e mantido em cache por até 5 minutos.
- Sem acesso ao perfil e sem sinal explícito, a disponibilidade permanece desconhecida. O programa não afirma que pode republicar.
- Um horário calculado indica quando tentar; o sucesso depende da aceitação da API. As regras do serviço podem mudar em versões futuras.
- Republicações manuais e automáticas compartilham trava e proteção contra repetição da mesma atualização aceita.
- Limites HTTP 429 interrompem o lote e respeitam `Retry-After`. Erros de autenticação ou anti-bot pausam a automação.

O tempo desde a atualização de cada anúncio avança a cada segundo no navegador, inclusive para anúncios antigos. O painel sincroniza com o servidor local a cada 10 segundos, reutilizando dados obtidos nos últimos 30 segundos. O horário mostrado só muda com informação recebida do Traderie; não é inventado após uma tentativa.

A detecção sem horário conhecido pode levar até o próximo ciclo, além do tempo de rede. Não há uma conexão de eventos em tempo real do Traderie confirmada neste projeto.

## Outros recursos

A navegação tem apenas **Anúncios** e **Usuário**. Ofertas e conversas continuam disponíveis no contexto de um anúncio. Agrupamento, exclusão com confirmação, sons opcionais e rotinas de rotação foram preservados. As rotinas de rotação criam outro anúncio e removem o anterior; são diferentes da republicação normal.

## Credenciais e rede

O token de sessão é recebido no formulário local ou por `TRADERIE_AUTH` e permanece na memória do processo. Não está incluído no código, no ZIP ou na configuração salva. A variável de ambiente é usada na reconexão de uma conta previamente configurada. A automação começa desativada após reiniciar.

Para acesso na nuvem, permita `traderie.com` e `cdn.nookazon.com` nas configurações de rede. Isso não elimina bloqueios impostos pelo próprio site. CAPTCHA e Cloudflare não são contornados.

**Validação desta versão:** catálogo real consultado em espécies, plushies e paletas, incluindo paginação, imagens e metadados de slots. A pesquisa por Mijusuima confirmou o tipo `Creatures` e a propriedade de espécie/slot 828, que substitui o valor fixo antigo. A conta de teste retornou uma lista pública de anúncios vazia. Testes Python e testes de navegador validam criação e automação com respostas simuladas; publicação, autenticação do token e republicação reais não foram executadas. Bloqueios de rede/Cloudflare ocorreram em algumas consultas, mas as chamadas finais com o cliente do projeto funcionaram.

O token fornecido não foi incorporado ao pacote. Imagens podem ser recusadas pelo CDN; nesse caso o painel mostra um marcador.

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

Para verificar somente leituras do catálogo real, execute `tests/live_catalog_smoke.py` da mesma forma, com o painel aberto.

O teste `browser_smoke.py` intercepta as respostas da API no navegador; ele valida seleção, payload de criação, categorias, recuperação de erros, relógios, teclado e telas de desktop/celular sem publicar anúncios reais. As imagens geradas são exemplos com dados simulados.

Arquivos principais: `app.py` (servidor e automação), `traderie.py` (cliente HTTP), `static/` (interface) e `tests/` (regressões).
